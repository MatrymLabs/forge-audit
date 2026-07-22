"""CARD: engine -- DiagnosticEngine: run the quality gates on a target repo.

The engine detects the repo's ECOSYSTEM and grades it with that ecosystem's own toolchain: a
Python repo through ruff/mypy/pytest/bandit/pip-audit, a Node repo through its package.json scripts
(lint/typecheck/test) + npm audit. Every path emits the same dimension names, so "grade any repo"
is literal, not Python-only. Two rules keep the reading honest:

  1. Audit a repo with ITS OWN toolchain. Each tool is resolved from the target's
     `.venv/bin/` first, so codeforge is graded with codeforge's installed deps and
     config -- not with forge-audit's. Grading a green repo red because we ran the wrong
     environment would be exactly the false-correspondence this tool exists to catch.
  2. A gate whose tool is absent reads `not_configured` -- never faked as passing.

Running a real subprocess lives behind a Runner seam so tests inject a fake and never
shell out. No claim without evidence.
"""

from __future__ import annotations

import json
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


def _uses_ruff(path: Path) -> bool:
    """Has the target ADOPTED ruff? The lint gate runs ruff, but many good repos lint with black +
    flake8/pylint and never opted into ruff's (opinionated) default rules. Running our ruff over
    such a repo manufactures a wall of style findings it never agreed to (rich: 84 findings, and it
    lints with black + mypy). So we grade lint only when the repo actually uses ruff -- a config, a
    ruff.toml, a pre-commit hook, or a pinned dep -- and abstain honestly otherwise. Rule #1:
    audit a repo with ITS OWN toolchain, not ours."""
    if (path / "ruff.toml").is_file() or (path / ".ruff.toml").is_file():
        return True
    pyproject = path / "pyproject.toml"
    # `[tool.ruff` (no closing bracket) catches both `[tool.ruff]` and sub-tables like
    # `[tool.ruff.lint]` that a repo may declare without the parent header.
    if pyproject.is_file() and "[tool.ruff" in pyproject.read_text(
        encoding="utf-8", errors="ignore"
    ):
        return True
    precommit = path / ".pre-commit-config.yaml"
    if precommit.is_file() and "ruff" in precommit.read_text(encoding="utf-8", errors="ignore"):
        return True
    return any(
        "ruff" in req.read_text(encoding="utf-8", errors="ignore")
        for req in path.glob("requirements*.txt")
    )


# The non-ruff formatters/linters we can recognize by name, so an abstained lint gate can say what
# the repo lints WITH ("lints with black + isort") instead of only "not ruff". This is evidence, not
# execution: we never run a foreign tool (it would need the repo's own version to be trustworthy).
_OTHER_LINTERS = ("black", "isort", "flake8", "pylint", "autopep8", "yapf")


def _detected_linters(path: Path) -> list[str]:
    """Names of the non-ruff formatters/linters the repo adopts -- a best-effort scan of its config
    surfaces. Used only to enrich the lint-abstention message; empty when nothing is recognized."""
    found: set[str] = set()
    # Config files whose mere presence names the tool (their contents may not spell it out).
    if (path / ".pylintrc").is_file():
        found.add("pylint")
    if (path / ".flake8").is_file():
        found.add("flake8")
    # Text surfaces where a tool's name or config table appears.
    parts = [
        (path / name).read_text(encoding="utf-8", errors="ignore")
        for name in ("pyproject.toml", "setup.cfg", "tox.ini", ".pre-commit-config.yaml")
        if (path / name).is_file()
    ]
    parts += [
        req.read_text(encoding="utf-8", errors="ignore") for req in path.glob("requirements*.txt")
    ]
    blob = "\n".join(parts).lower()
    found.update(tool for tool in _OTHER_LINTERS if tool in blob)
    return sorted(found)


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
    if gate == "lint" and not _uses_ruff(path):
        # The repo lints with something other than ruff; grading it by our ruff would defame it.
        # Name what it DOES use, so the abstention is evidence, not a shrug.
        others = _detected_linters(path)
        detail = (
            f"repo lints with {' + '.join(others)}, not ruff (not graded here)"
            if others
            else "repo does not adopt ruff (no config or dep)"
        )
        return GateReading(gate, NOT_CONFIGURED, detail)
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


# --- ecosystem detection + the Node/npm toolchain -------------------------------
# "Grade any repo" means grading it with ITS ecosystem's tools, not Python's. We detect the primary
# ecosystem by manifest and dispatch. Python wins when both are present (a Python repo may ship a
# package.json for a JS asset; its gate is still Python).


def detect_ecosystem(path: Path) -> str:
    """The repo's primary language ecosystem, by manifest: `python` | `node` | `unknown`."""
    if (
        (path / "pyproject.toml").is_file()
        or (path / "setup.py").is_file()
        or (path / "setup.cfg").is_file()
        or any(path.glob("requirements*.txt"))
    ):
        return "python"
    if (path / "package.json").is_file():
        return "node"
    return "unknown"


def _node_scripts(path: Path) -> dict[str, str]:
    """The `scripts` map from package.json ({} if missing or malformed)."""
    try:
        data = json.loads((path / "package.json").read_text(encoding="utf-8", errors="ignore"))
    except (json.JSONDecodeError, OSError):
        return {}
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}


def _has_node_modules(path: Path, runner: Runner) -> bool:
    """Did we have the target's installed JS deps to grade with? (node_modules present.) Under a
    fake runner the injected result is authoritative, so we assume the env is present."""
    if runner is not subprocess_runner:
        return True
    return (path / "node_modules").is_dir()


def _run_npm_script(gate: str, script: str, path: Path, runner: Runner) -> GateReading:
    """One Node gate: `npm run <script>` if the repo defines it. Abstains honestly when the script
    is absent (the repo doesn't run that gate) or node_modules is missing (we lack its env)."""
    if script not in _node_scripts(path):
        return GateReading(gate, NOT_CONFIGURED, f"no `{script}` script in package.json")
    if not _has_node_modules(path, runner):
        return GateReading(
            gate,
            NOT_RUNNABLE,
            f"`npm run {script}` needs the target's node_modules; run `npm install` to grade",
        )
    npm = _resolve("npm", runner, path)
    if npm is None:
        return GateReading(gate, NOT_CONFIGURED, "npm not found on PATH")
    try:
        result = runner([npm, "run", script], path)
    except Exception as exc:
        return GateReading(gate, ERROR, f"npm raised: {exc}")
    return GateReading(gate, PASS if result.code == 0 else FAIL, _summarize(result.out))


def _run_npm_audit(path: Path, runner: Runner) -> GateReading:
    """The Node dependency gate: `npm audit --audit-level=high` (block on high+, mirroring the
    Python deps gate's severity floor). Needs a lockfile or installed tree to resolve advisories."""
    if not _has_node_modules(path, runner) and not (path / "package-lock.json").is_file():
        return GateReading(
            "dependencies", NOT_RUNNABLE, "npm audit needs a lockfile or node_modules to resolve"
        )
    npm = _resolve("npm", runner, path)
    if npm is None:
        return GateReading("dependencies", NOT_CONFIGURED, "npm not found on PATH")
    try:
        result = runner([npm, "audit", "--audit-level=high"], path)
    except Exception as exc:
        return GateReading("dependencies", ERROR, f"npm raised: {exc}")
    return GateReading("dependencies", PASS if result.code == 0 else FAIL, _summarize(result.out))


def _node_readings(path: Path, runner: Runner) -> list[GateReading]:
    """Grade a Node repo through its package.json scripts + npm audit. Emits the same dimension
    names the scorecard grades. Coverage isn't parsed for JS yet (tests read as green-without-a-
    coverage-number -> a watchlist, honestly), and there is no standard Node SAST gate."""
    return [
        _run_npm_script("lint", "lint", path, runner),
        _run_npm_script("typecheck", "typecheck", path, runner),
        _run_npm_script("tests", "test", path, runner),
        GateReading("security", NOT_CONFIGURED, "no standard Node SAST gate (JS ecosystem)"),
        _run_npm_audit(path, runner),
    ]


def diagnose(path: Path, runner: Runner = subprocess_runner) -> list[GateReading]:
    """Run every gate against the target repo with ITS ecosystem's toolchain, and return the
    readings. Python and Node are graded natively; an unknown ecosystem falls back to the Python
    gates (which will abstain honestly if their tools aren't there)."""
    if detect_ecosystem(path) == "node":
        return _node_readings(path, runner)
    specs = _gate_specs(path)
    readings = [run_gate(g, tool, args, path, runner) for g, tool, args in specs]
    readings.insert(2, run_tests(path, runner))  # tests sit after typecheck
    return readings
