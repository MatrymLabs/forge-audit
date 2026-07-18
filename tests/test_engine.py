"""Test twin for engine.py -- DiagnosticEngine gate runs (all via the fake Runner)."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_bandit_excludes_test_dirs_by_default_but_defers_to_a_repos_own_config(
    tmp_path: Path,
) -> None:
    from forge_audit.engine import _bandit_args

    # No config: test dirs are excluded -- bandit grades shipped code, not test fixtures whose
    # pickle/subprocess/assert would fail a foreign repo on its own tests (httpx's 8 noise).
    default_args = _bandit_args(tmp_path)
    exclude_default = default_args[default_args.index("--exclude") + 1]
    assert "./tests" in exclude_default and "./test" in exclude_default
    # With [tool.bandit], the repo owns its scope -- we do NOT impose a test exclude over it.
    (tmp_path / "pyproject.toml").write_text("[tool.bandit]\nskips = ['B101']\n")
    args = _bandit_args(tmp_path)
    exclude_configured = args[args.index("--exclude") + 1]
    assert "./tests" not in exclude_configured  # honor the repo's own scope, don't override it


# --- Foreign-repo honesty: lint abstains when the repo doesn't adopt ruff ------------------------


def test_uses_ruff_detects_each_adoption_signal(tmp_path: Path) -> None:
    from forge_audit.engine import _uses_ruff

    assert _uses_ruff(tmp_path) is False  # a black+mypy repo like rich: no ruff anywhere
    (tmp_path / "pyproject.toml").write_text("[tool.ruff.lint]\nselect = ['E']\n", encoding="utf-8")
    assert _uses_ruff(tmp_path) is True  # sub-table counts, not just [tool.ruff]
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
    assert _uses_ruff(tmp_path) is True
    (tmp_path / "ruff.toml").unlink()
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n", encoding="utf-8"
    )
    assert _uses_ruff(tmp_path) is True  # a pre-commit hook counts
    (tmp_path / ".pre-commit-config.yaml").unlink()
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.15.0\n", encoding="utf-8")
    assert _uses_ruff(tmp_path) is True


def test_lint_abstains_when_the_repo_does_not_adopt_ruff(tmp_path: Path) -> None:
    # rich lints with black+mypy; our ruff would manufacture 84 findings it never opted into.
    # Grade not_configured (a visible gap), never fail -- do not impose a linter the repo rejected.
    runner = FakeRunner({"ruff": CommandResult(1, "E712 comparison to True")})
    reading = run_gate("lint", "ruff", ["check", "."], tmp_path, runner)
    assert reading.status == NOT_CONFIGURED
    assert "does not adopt ruff" in reading.detail


def test_lint_still_grades_a_repo_that_adopts_ruff(tmp_path: Path) -> None:
    # A repo that DOES use ruff is graded normally -- abstention never masks a real lint failure.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    runner = FakeRunner({"ruff": CommandResult(1, "E501 line too long")})
    reading = run_gate("lint", "ruff", ["check", "."], tmp_path, runner)
    assert reading.status == FAIL
    assert "E501" in reading.detail


# --- Foreign-repo honesty: no target env -> not_runnable, never a false fail ----------------------


def test_has_target_env_true_only_when_the_targets_venv_holds_the_tool(tmp_path: Path) -> None:
    # Under the real runner, "we have the env" means the tool lives in the TARGET's own .venv.
    from forge_audit.engine import _has_target_env, subprocess_runner

    assert _has_target_env("mypy", subprocess_runner, tmp_path) is False  # a bare clone: no .venv
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "mypy").write_text("#!/bin/sh\n")
    assert _has_target_env("mypy", subprocess_runner, tmp_path) is True
    # Under a fake runner the injected result is authoritative -> assume the env is present.
    assert _has_target_env("mypy", FakeRunner({}), tmp_path) is True


def test_mypy_without_the_targets_env_reads_not_runnable_not_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # httpx's real fault: `ignore_missing_imports` turned absent deps into `Any`, so mypy emitted 24
    # untyped-decorator / unused-ignore / subclass-of-Any errors. None is a stub-import string, so
    # the old guard missed them and graded a green repo FAIL. Absent the target env, this is a gap.
    import forge_audit.engine as engine

    monkeypatch.setattr(engine, "_has_target_env", lambda *a, **k: False)
    out = 'httpx/_main.py:313: error: Untyped decorator makes "main" untyped  [untyped-decorator]'
    reading = run_gate(
        "typecheck", "mypy", ["."], tmp_path, FakeRunner({"mypy": CommandResult(1, out)})
    )
    assert reading.status == NOT_RUNNABLE
    assert "no .venv" in reading.detail


def test_mypy_with_the_targets_env_still_reads_a_real_type_error_as_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The escape hatch must not swallow genuine failures: WITH the target's env, a real error fails.
    import forge_audit.engine as engine

    monkeypatch.setattr(engine, "_has_target_env", lambda *a, **k: True)
    out = "x.py:1: error: Incompatible return value type  [return-value]\nFound 1 error in 1 file"
    reading = run_gate(
        "typecheck", "mypy", ["."], tmp_path, FakeRunner({"mypy": CommandResult(1, out)})
    )
    assert reading.status == FAIL


def test_pytest_without_the_targets_env_reads_not_runnable_not_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A red suite we ran without the repo's deps is our missing env, not the repo's bug. Catches
    # failures the collection-error strings miss (a test that runs but errors on an absent dep).
    import forge_audit.engine as engine

    monkeypatch.setattr(engine, "_has_target_env", lambda *a, **k: False)
    reading = run_tests(tmp_path, FakeRunner({"pytest": CommandResult(1, "1 failed in 0.10s")}))
    assert reading.status == NOT_RUNNABLE
    assert "no .venv" in reading.detail


# --- Foreign-repo honesty: a security FAIL must quote its real evidence, not boilerplate ----------

_BANDIT_TAIL = """Run metrics:
\tTotal issues (by severity):
\t\tUndefined: 0
\t\tLow: 1324
\t\tMedium: 8
\t\tHigh: 1
\tTotal issues (by confidence):
\t\tUndefined: 0
\t\tLow: 0
\t\tMedium: 27
\t\tHigh: 1306
Files skipped (0):"""


def test_bandit_failure_evidence_quotes_the_real_severity_counts() -> None:
    # The old evidence was bandit's last line -- "Files skipped (0):" -- meaningless for a verdict.
    reading = run_gate(
        "security",
        "bandit",
        ["-r", "."],
        HERE,
        FakeRunner({"bandit": CommandResult(1, _BANDIT_TAIL)}),
    )
    assert reading.status == FAIL
    assert reading.detail == "1 high, 8 medium severity issue(s)"
    assert "Files skipped" not in reading.detail


def test_bandit_severity_counts_ignore_the_confidence_block() -> None:
    # The "by confidence" block repeats High/Medium (1306/27); a naive match would report those as
    # severities. Isolate the severity block so 1 high / 8 medium is what we quote.
    from forge_audit.engine import _summarize_bandit

    assert _summarize_bandit(_BANDIT_TAIL) == "1 high, 8 medium severity issue(s)"
    assert _summarize_bandit("no severity tally here") is None
