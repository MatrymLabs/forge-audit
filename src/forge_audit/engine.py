"""CARD: engine -- DiagnosticEngine: run the quality gates on a target repo.

The engine ignites each gate (ruff, mypy, pytest --cov, bandit, pip-audit) against a
target repository and returns a GateReading per gate. Two rules keep the reading honest:

  1. Audit a repo with ITS OWN toolchain. Each tool is resolved from the target's
     `.venv/bin/` first, so codeforge is graded with codeforge's installed deps and
     config -- not with forge-audit's. Grading a green repo red because we ran the wrong
     environment would be exactly the false-correspondence this tool exists to catch.
  2. A gate whose tool is absent reads `not_configured` -- never faked as passing.

Running a real subprocess lives behind a Runner seam so tests inject a fake and never
shell out. No claim without evidence.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# --- Gate outcomes ---------------------------------------------------------------
PASS = "pass"  # nosec B105 -- a gate verdict, not a password
FAIL = "fail"
NOT_CONFIGURED = "not_configured"  # the tool itself is absent (no venv or PATH)
NOT_RUNNABLE = "not_runnable"  # the tool ran but could not exercise the code (deps/env absent)
ERROR = "error"

# Auditing a repo we did NOT build, we may lack its dev environment. A gate that could not RUN the
# code (imports unresolved, suite uncollectable) is not evidence the repo is broken -- grading it a
# `fail` would defame a project whose own CI is green. These markers separate "could not run here"
# from "ran and failed", so a foreign-repo audit stays honest. A genuinely failing suite does not
# emit an import/collection error, so this never masks a real failure.
_PYTEST_UNRUNNABLE = (
    "no module named",
    "modulenotfounderror",
    "importerror",
    "error collecting",
    "errors during collection",
    "internalerror",
)
# mypy could not resolve the code's own imports (third-party deps/stubs absent), so its type verdict
# is untrustworthy -- a missing environment, not a genuine type error.
_MYPY_UNRUNNABLE = (
    "cannot find implementation or library stub",
    "cannot find module",
    "import-not-found",
)


def _matches(out: str, markers: tuple[str, ...]) -> bool:
    low = out.lower()
    return any(marker in low for marker in markers)


@dataclass(frozen=True)
class GateReading:
    """One gate run against the target: what it is, how it went, the evidence."""

    gate: str
    status: str  # pass | fail | not_configured | error
    detail: str
    coverage: float | None = None  # only pytest --cov populates this


@dataclass(frozen=True)
class CommandResult:
    """The raw result of a shelled command -- the Runner seam's return type."""

    code: int
    out: str


# A Runner takes (argv, cwd) and returns a CommandResult. subprocess by default;
# tests inject a fake so the suite never touches a shell, a network, or a real tool.
Runner = Callable[[list[str], Path], CommandResult]


def subprocess_runner(argv: list[str], cwd: Path) -> CommandResult:
    """The production Runner: run argv in cwd, merge stderr into stdout, capture text."""
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=600, check=False)
    return CommandResult(proc.returncode, proc.stdout + proc.stderr)


def _resolve(tool: str, runner: Runner, path: Path) -> str | None:
    """Locate a tool for the REAL runner: the target's own venv first, then PATH; None if
    absent. Under a fake runner the bare name is returned so injected tests stay simple."""
    if runner is not subprocess_runner:
        return tool
    venv_tool = path / ".venv" / "bin" / tool
    if venv_tool.is_file():
        return str(venv_tool)
    return shutil.which(tool)


# Gates whose verdict is only trustworthy when run with the target's OWN installed deps.
# mypy (under the near-universal `ignore_missing_imports`) silently degrades absent third-party
# imports to `Any` and then emits a cascade of untyped-decorator / unused-ignore / subclass-of-Any
# errors; pytest cannot even import the suite. Those are artifacts of a missing environment, not the
# repo's real defects -- grading them a `fail` would defame a project whose own CI is green. When we
# lack the target's env, such a gate reads `not_runnable` (a measurement gap), never `fail`.
_NEEDS_TARGET_ENV = ("mypy", "pytest")


def _has_target_env(tool: str, runner: Runner, path: Path) -> bool:
    """Did we have the TARGET's own environment to grade this gate with? Under the real runner that
    means the tool resolved from the target's `.venv` (its installed deps); a foreign repo we only
    cloned has none. Under a fake runner the injected result is authoritative, so we assume the env
    is present and grade the canned result exactly as given (keeps the suite deterministic)."""
    if runner is not subprocess_runner:
        return True
    return (path / ".venv" / "bin" / tool).is_file()


# The TOTAL row has a variable column count: flat coverage is `TOTAL Stmts Miss Cover`, but BRANCH
# coverage (the stricter kind) is `TOTAL Stmts Miss Branch BrPart Cover`. Match any number of
# integer columns before the final percent, so a repo isn't undersold for using branch coverage.
_COVERAGE_RE = re.compile(r"TOTAL\s+(?:\d+\s+)+(\d+)%")


def _parse_coverage(out: str) -> float | None:
    """Pull the TOTAL coverage percent out of pytest-cov's terminal report."""
    match = _COVERAGE_RE.search(out)
    return float(match.group(1)) if match else None


def _bandit_args(path: Path) -> list[str]:
    """Fair bandit invocation: exclude the venv/git, gate on real (medium+) severity, and
    honor the target's own [tool.bandit] config (its reviewed suppressions) when declared.

    `--severity-level medium` is deliberate: low-severity findings (e.g. subprocess use)
    are noise every mature repo triages, not vulnerabilities. Gating on them would fail
    nearly every real codebase and make the verdict meaningless. We block on what matters.

    Test directories are excluded when the repo has NO bandit config of its own. bandit grades
    shipped code, and test fixtures routinely use pickle/subprocess/assert that are not deployment
    risks -- scanning them would fail a foreign repo on its own test suite (httpx: 8 of 9 medium+
    findings were pickle in tests, 1 real finding in product code). A repo that DECLARES
    [tool.bandit] sets its own scope, so we honor its config and impose nothing beyond infra dirs.
    """
    excludes = "./.venv,./.git"
    pyproject = path / "pyproject.toml"
    has_config = pyproject.is_file() and "[tool.bandit]" in pyproject.read_text(
        encoding="utf-8", errors="ignore"
    )
    if not has_config:
        excludes += ",./tests,./test"
    args = ["-r", ".", "-q", "--severity-level", "medium", "--exclude", excludes]
    if has_config:
        args = ["-c", "pyproject.toml", *args]
    return args


def _mypy_args(path: Path) -> list[str]:
    """mypy invocation that HONORS the target's own scope instead of imposing ours.

    A single hardcoded `mypy .` mis-audits real repos and grades type-clean ones red -- the
    exact false-correspondence this tool exists to catch:
      - a src-layout repo installed editable resolves its own first-party packages to the
        installed dist (no `py.typed`) and reads a wall of spurious `import-untyped`;
      - `mypy .` pulls in dirs a repo's real gate excludes (e.g. an `e2e/` with a second
        `conftest.py`), raising a "Duplicate module" collision that is not a type error.

    So when the target declares its scope in `[tool.mypy] files`, run mypy config-driven
    (no positional args): mypy reads that scope and the repo's own flags, and we grade it
    exactly as its own gate does. Only when no scope is declared do we fall back to a plain
    best-effort `mypy .`.
    """
    pyproject = path / "pyproject.toml"
    if pyproject.is_file():
        try:
            config = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="ignore"))
        except tomllib.TOMLDecodeError:
            config = {}
        if config.get("tool", {}).get("mypy", {}).get("files"):
            return []  # no positional args -> mypy honors `files` (and flags) from the config
    return ["."]


# --- The gates, in cheapest-first order (tests handled separately for coverage) --
# Each entry: (gate name, tool, args-after-the-tool).
def _gate_specs(path: Path) -> tuple[tuple[str, str, list[str]], ...]:
    return (
        ("lint", "ruff", ["check", "."]),
        ("typecheck", "mypy", _mypy_args(path)),
        ("security", "bandit", _bandit_args(path)),
        ("dependencies", "pip-audit", ["--skip-editable"]),
    )


def run_gate(gate: str, tool: str, args: list[str], path: Path, runner: Runner) -> GateReading:
    """Ignite one gate: skip honestly if its tool is absent, else run and read the code."""
    resolved = _resolve(tool, runner, path)
    if resolved is None:
        return GateReading(gate, NOT_CONFIGURED, f"{tool} not found (no venv or PATH)")
    try:
        result = runner([resolved, *args], path)
    except Exception as exc:  # a broken tool must surface, never masquerade as pass
        return GateReading(gate, ERROR, f"{tool} raised: {exc}")
    if result.code != 0 and tool == "mypy" and _matches(result.out, _MYPY_UNRUNNABLE):
        # mypy could not resolve the code's imports -- a missing env, not a real type error.
        return GateReading(
            gate, NOT_RUNNABLE, f"imports unresolved (deps absent): {_summarize(result.out)}"
        )
    if result.code != 0 and tool in _NEEDS_TARGET_ENV and not _has_target_env(tool, runner, path):
        # We graded without the target's own deps; its `Any`-cascade errors are not real defects.
        return GateReading(
            gate,
            NOT_RUNNABLE,
            f"{tool} needs the target's installed deps to grade; no .venv found "
            "(audit with the repo's own environment for a verdict)",
        )
    status = PASS if result.code == 0 else FAIL
    return GateReading(gate, status, _evidence(tool, result.out))


def run_tests(path: Path, runner: Runner) -> GateReading:
    """The tests+coverage gate: pytest --cov, parsing the TOTAL percent as evidence."""
    resolved = _resolve("pytest", runner, path)
    if resolved is None:
        return GateReading("tests", NOT_CONFIGURED, "pytest not found (no venv or PATH)")
    try:
        result = runner([resolved, "--cov", "--cov-report=term-missing", "-q"], path)
    except Exception as exc:
        return GateReading("tests", ERROR, f"pytest raised: {exc}")
    if result.code != 0 and _matches(result.out, _PYTEST_UNRUNNABLE):
        # The suite could not be imported/collected here (deps absent) -- not a real failure.
        return GateReading(
            "tests", NOT_RUNNABLE, f"suite not collectable (deps absent): {_summarize(result.out)}"
        )
    if result.code != 0 and not _has_target_env("pytest", runner, path):
        # We graded without the target's own deps; a red suite here is our missing env, not its bug.
        return GateReading(
            "tests",
            NOT_RUNNABLE,
            "suite needs the target's installed deps to run; no .venv found "
            "(audit with the repo's own environment for a verdict)",
        )
    status = PASS if result.code == 0 else FAIL
    return GateReading("tests", status, _summarize(result.out), _parse_coverage(result.out))


def _summarize(out: str) -> str:
    """The last non-empty line of output -- enough evidence to quote, not a wall of text."""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


# Bandit's last non-empty line is boilerplate ("Files skipped (0):"), so `_summarize` would quote
# nothing useful for a security FAIL. The real evidence is its severity tally. Isolate the "by
# severity" block first -- bandit prints an identically-shaped "by confidence" block right after it,
# and matching High/Medium across both would report the confidence counts (e.g. 1306) as severities.
_BANDIT_SEVERITY_BLOCK = re.compile(r"by severity\):(.*?)(?:by confidence\)|\Z)", re.DOTALL)
_BANDIT_SEVERITY_LINE = re.compile(r"^\s*(High|Medium):\s*(\d+)\s*$", re.MULTILINE)


def _summarize_bandit(out: str) -> str | None:
    """Pull bandit's High/Medium severity counts as evidence; None if the tally can't be found."""
    block = _BANDIT_SEVERITY_BLOCK.search(out)
    section = block.group(1) if block else out
    counts = {m.group(1).lower(): int(m.group(2)) for m in _BANDIT_SEVERITY_LINE.finditer(section)}
    parts = [f"{counts[sev]} {sev}" for sev in ("high", "medium") if counts.get(sev)]
    return f"{', '.join(parts)} severity issue(s)" if parts else None


def _evidence(tool: str, out: str) -> str:
    """The evidence line to quote for a gate. Bandit gets its severity tally (its last line is
    boilerplate); every other tool's last non-empty line is enough to stand as evidence."""
    if tool == "bandit":
        bandit_summary = _summarize_bandit(out)
        if bandit_summary is not None:
            return bandit_summary
    return _summarize(out)


def diagnose(path: Path, runner: Runner = subprocess_runner) -> list[GateReading]:
    """Run every gate against the target repo and return the readings in gate order."""
    specs = _gate_specs(path)
    readings = [run_gate(g, tool, args, path, runner) for g, tool, args in specs]
    readings.insert(2, run_tests(path, runner))  # tests sit after typecheck
    return readings
