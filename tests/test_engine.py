"""Test twin for engine.py -- DiagnosticEngine gate runs (all via the fake Runner)."""

from __future__ import annotations

from pathlib import Path

from forge_audit.engine import (
    ERROR,
    FAIL,
    NOT_CONFIGURED,
    NOT_RUNNABLE,
    PASS,
    CommandResult,
    diagnose,
    run_gate,
    run_tests,
)

from .conftest import FakeRunner, green

HERE = Path(".")


def test_a_green_repo_passes_every_gate() -> None:
    readings = {r.gate: r for r in diagnose(HERE, FakeRunner(green()))}
    assert set(readings) == {"lint", "typecheck", "tests", "security", "dependencies"}
    assert all(r.status == PASS for r in readings.values())


def test_coverage_percent_is_parsed_from_pytest_output() -> None:
    reading = run_tests(HERE, FakeRunner(green(coverage=73)))
    assert reading.coverage == 73.0


def test_branch_coverage_total_is_parsed_not_just_flat() -> None:
    from forge_audit.engine import _parse_coverage

    # Branch coverage adds Branch/BrPart columns; the TOTAL row must still parse.
    assert _parse_coverage("TOTAL   14570   445   2244   216   96%") == 96.0
    assert _parse_coverage("TOTAL   100   5   95%") == 95.0  # flat still works
    assert _parse_coverage("no total line here") is None


def test_pytest_import_error_reads_not_runnable_not_fail() -> None:
    # Auditing a foreign repo without its dev env: the suite cannot be imported. That is a
    # measurement gap, NOT evidence the repo's tests fail -- grading it fail would defame the repo.
    out = "ERROR collecting tests/test_x.py\nModuleNotFoundError: No module named 'trio'\n4 errors"
    reading = run_tests(HERE, FakeRunner({"pytest": CommandResult(2, out)}))
    assert reading.status == NOT_RUNNABLE


def test_a_genuine_test_failure_still_reads_fail() -> None:
    # A real failure (no import/collection error) still fails -- the fix never masks a red suite.
    reading = run_tests(HERE, FakeRunner({"pytest": CommandResult(1, "1 failed in 0.10s")}))
    assert reading.status == FAIL


def test_mypy_missing_stub_reads_not_runnable_not_fail() -> None:
    out = "src/x.py:1: error: Cannot find implementation or library stub for module named 'httpx'"
    reading = run_gate(
        "typecheck", "mypy", ["."], HERE, FakeRunner({"mypy": CommandResult(1, out)})
    )
    assert reading.status == NOT_RUNNABLE


def test_a_real_mypy_type_error_still_reads_fail() -> None:
    out = 'src/x.py:3: error: Incompatible return value type (got "int", expected "str")'
    reading = run_gate(
        "typecheck", "mypy", ["."], HERE, FakeRunner({"mypy": CommandResult(1, out)})
    )
    assert reading.status == FAIL


def test_a_nonzero_exit_is_reported_as_fail_not_swallowed() -> None:
    runner = FakeRunner({"ruff": CommandResult(1, "E501 line too long")})
    reading = run_gate("lint", "ruff", ["check", "."], HERE, runner)
    assert reading.status == FAIL
    assert "E501" in reading.detail


def test_a_raising_tool_surfaces_as_error_never_pass() -> None:
    def boom(argv: list[str], cwd: Path) -> CommandResult:
        raise RuntimeError("tool crashed")

    reading = run_gate("lint", "ruff", [], HERE, boom)
    assert reading.status == ERROR
    assert "crashed" in reading.detail


def test_a_missing_tool_reads_not_configured_under_the_real_runner() -> None:
    # subprocess_runner is the real one; a tool that cannot exist must skip honestly.
    from forge_audit.engine import subprocess_runner

    reading = run_gate("lint", "definitely-not-a-real-tool-xyz", ["nope"], HERE, subprocess_runner)
    assert reading.status == NOT_CONFIGURED


def test_no_test_output_yields_no_coverage_number() -> None:
    reading = run_tests(HERE, FakeRunner({"pytest": CommandResult(0, "1 passed")}))
    assert reading.status == PASS
    assert reading.coverage is None


def test_a_repos_own_venv_toolchain_is_preferred(tmp_path: Path) -> None:
    # The honest fix: audit a repo with ITS tools. A venv binary must win over PATH.
    from forge_audit.engine import _resolve, subprocess_runner

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "ruff").write_text("#!/bin/sh\n")
    resolved = _resolve("ruff", subprocess_runner, tmp_path)
    assert resolved == str(venv_bin / "ruff")


def test_typecheck_honors_the_targets_declared_mypy_scope(tmp_path: Path) -> None:
    # A repo that declares `[tool.mypy] files` is audited config-driven (no positional
    # args), so mypy honors its scope and flags -- graded exactly as its own gate runs.
    # Hardcoding `mypy .` instead false-fails src-layout installs and dirs the repo excludes.
    from forge_audit.engine import _gate_specs, _mypy_args

    (tmp_path / "pyproject.toml").write_text(
        '[tool.mypy]\nfiles = ["src", "tests"]\n', encoding="utf-8"
    )
    assert _mypy_args(tmp_path) == []
    typecheck = next(spec for spec in _gate_specs(tmp_path) if spec[0] == "typecheck")
    assert typecheck[1] == "mypy"
    assert typecheck[2] == []  # config-driven: no imposed scope or flags


def test_typecheck_falls_back_to_dot_when_no_scope_is_declared(tmp_path: Path) -> None:
    from forge_audit.engine import _mypy_args

    # No pyproject at all -> best-effort whole-tree scan.
    assert _mypy_args(tmp_path) == ["."]
    # A pyproject with [tool.mypy] but no `files` -> still the fallback.
    (tmp_path / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n", encoding="utf-8")
    assert _mypy_args(tmp_path) == ["."]


def test_typecheck_tolerates_a_malformed_pyproject(tmp_path: Path) -> None:
    from forge_audit.engine import _mypy_args

    # A broken TOML must not crash the audit -- fall back, don't raise.
    (tmp_path / "pyproject.toml").write_text("[tool.mypy\nfiles = broken", encoding="utf-8")
    assert _mypy_args(tmp_path) == ["."]


def test_bandit_honors_the_targets_own_config_and_excludes_the_venv(tmp_path: Path) -> None:
    from forge_audit.engine import _bandit_args

    # No config -> just the safe excludes.
    assert "--exclude" in _bandit_args(tmp_path)
    assert "-c" not in _bandit_args(tmp_path)
    # A repo that declares [tool.bandit] -> its reviewed suppressions are honored.
    (tmp_path / "pyproject.toml").write_text("[tool.bandit]\nskips = ['B101']\n")
    args = _bandit_args(tmp_path)
    assert args[:2] == ["-c", "pyproject.toml"]
