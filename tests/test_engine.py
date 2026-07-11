"""Test twin for engine.py -- DiagnosticEngine gate runs (all via the fake Runner)."""

from __future__ import annotations

from pathlib import Path

from forge_audit.engine import (
    ERROR,
    FAIL,
    NOT_CONFIGURED,
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


def test_typecheck_resolves_package_bases_so_duplicate_conftest_is_not_a_false_fail() -> None:
    # Regression pin: `mypy .` over a repo with two `conftest.py` (root + e2e/) raises
    # "Duplicate module" and reads *fail* -- a resolution collision, not a type error. The
    # package-base flags let mypy resolve them as distinct modules and return the true
    # verdict. Dropping either flag reintroduces the false negative this tool exists to catch.
    from forge_audit.engine import _gate_specs

    typecheck = next(spec for spec in _gate_specs(Path(".")) if spec[0] == "typecheck")
    _, tool, args = typecheck
    assert tool == "mypy"
    assert "--namespace-packages" in args
    assert "--explicit-package-bases" in args


def test_bandit_honors_the_targets_own_config_and_excludes_the_venv(tmp_path: Path) -> None:
    from forge_audit.engine import _bandit_args

    # No config -> just the safe excludes.
    assert "--exclude" in _bandit_args(tmp_path)
    assert "-c" not in _bandit_args(tmp_path)
    # A repo that declares [tool.bandit] -> its reviewed suppressions are honored.
    (tmp_path / "pyproject.toml").write_text("[tool.bandit]\nskips = ['B101']\n")
    args = _bandit_args(tmp_path)
    assert args[:2] == ["-c", "pyproject.toml"]
