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
    """
    args = ["-r", ".", "-q", "--severity-level", "medium", "--exclude", "./.venv,./.git"]
    pyproject = path / "pyproject.toml"
    if pyproject.is_file() and "[tool.bandit]" in pyproject.read_text(
        encoding="utf-8", errors="ignore"
    ):
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
    status = PASS if result.code == 0 else FAIL
    return GateReading(gate, status, _summarize(result.out))


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
    status = PASS if result.code == 0 else FAIL
    return GateReading("tests", status, _summarize(result.out), _parse_coverage(result.out))


def _summarize(out: str) -> str:
    """The last non-empty line of output -- enough evidence to quote, not a wall of text."""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def diagnose(path: Path, runner: Runner = subprocess_runner) -> list[GateReading]:
    """Run every gate against the target repo and return the readings in gate order."""
    specs = _gate_specs(path)
    readings = [run_gate(g, tool, args, path, runner) for g, tool, args in specs]
    readings.insert(2, run_tests(path, runner))  # tests sit after typecheck
    return readings
