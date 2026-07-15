"""CARD: scorecard -- EvidenceLedger: turn gate readings into a graded JSON verdict.

The ledger weighs the DiagnosticEngine's readings and the forge's collaboration signals
against objective STAGE THRESHOLDS (not vibes), and forges a scorecard: an overall
verdict (pass | watchlist | fail), per-dimension verdicts with quoted evidence, the role
signals the evidence supports, and the top gaps to close next. Thresholds are baked in so
two runs of the same repo grade identically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from forge_audit.engine import (
    NOT_CONFIGURED,
    PASS,
    GateReading,
    Runner,
    diagnose,
    subprocess_runner,
)
from forge_audit.github import OfflineProbe, RepoProbe, RepoSignals

# --- Verdict vocabulary ----------------------------------------------------------
PASS_V = "pass"  # nosec B105 -- a verdict word, not a password
WATCHLIST = "watchlist"
FAIL_V = "fail"

# --- Stage thresholds (baked in; the gate is objective) --------------------------
# coverage floor and minimum CI workflow count per stage.
STAGES: dict[str, dict[str, int]] = {
    "entry": {"coverage": 70, "workflows": 1},
    "intermediate": {"coverage": 80, "workflows": 2},
    "advanced": {"coverage": 85, "workflows": 3},
}


@dataclass(frozen=True)
class Dimension:
    """One graded axis of the scorecard: its verdict and the evidence behind it."""

    name: str
    verdict: str  # pass | watchlist | fail
    evidence: str


@dataclass
class Scorecard:
    """The forged verdict on a repo -- serializes straight to the framework JSON schema."""

    repo: str
    stage: str
    verdict: str
    dimensions: list[Dimension]
    role_signals: list[str]
    top_gaps: list[str]
    top_strengths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _grade_tests(reading: GateReading, floor: int) -> Dimension:
    """Tests+coverage: fail if the suite is red or absent; watchlist if below the floor."""
    if reading.status == NOT_CONFIGURED:
        return Dimension("tests", FAIL_V, "no test suite detected")
    if reading.status != PASS:
        return Dimension("tests", FAIL_V, f"suite not green: {reading.detail}")
    cov = reading.coverage
    if cov is None:
        return Dimension("tests", WATCHLIST, "green suite, but no coverage measured")
    if cov < floor:
        return Dimension("tests", WATCHLIST, f"coverage {cov:.0f}% < {floor}% floor")
    return Dimension("tests", PASS_V, f"green suite, coverage {cov:.0f}% ≥ {floor}%")


def _grade_gate(name: str, reading: GateReading) -> Dimension:
    """A hard gate (lint/typecheck/security/deps): pass green, watchlist absent, else fail."""
    if reading.status == NOT_CONFIGURED:
        return Dimension(name, WATCHLIST, reading.detail)
    if reading.status == PASS:
        return Dimension(name, PASS_V, "clean")
    return Dimension(name, FAIL_V, reading.detail)


def _grade_ci(signals: RepoSignals, minimum: int) -> Dimension:
    """CI wiring: pass at/above the stage's workflow minimum, watchlist below, fail at zero."""
    n = signals.workflows
    if n == 0:
        return Dimension("ci", FAIL_V, "no CI workflows found")
    if n < minimum:
        return Dimension("ci", WATCHLIST, f"{n} workflow(s) < {minimum} for this stage")
    return Dimension("ci", PASS_V, f"{n} CI workflow(s)")


def _grade_performance(signals: RepoSignals) -> Dimension:
    """Performance evidence: a benchmark/profiling artifact is the signal; else a watchlist note.
    Presence-graded like ci/collaboration - an absent benchmark is a visible gap, not a failure
    (forge-audit grades any repo, and not every good repo benchmarks)."""
    if signals.performance:
        return Dimension("performance", PASS_V, f"benchmark artifact: {signals.performance}")
    return Dimension("performance", WATCHLIST, "no benchmark/profiling artifact found")


def _grade_collaboration(signals: RepoSignals) -> Dimension:
    """The collaboration loop: at least one merged PR is the signal; else a watchlist note."""
    if signals.merged_prs > 0:
        return Dimension("collaboration", PASS_V, f"{signals.merged_prs} merged PR(s)")
    return Dimension("collaboration", WATCHLIST, "no merged-PR loop observed (or offline)")


# Which passing dimensions vouch for which role. Evidence-first: a signal is claimed
# only when the dimension that proves it passes.
_ROLE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "testing": ("tests",),
    "security": ("security", "dependencies"),
    "backend": ("typecheck", "lint"),
    "devops": ("ci",),
    "collaboration": ("collaboration",),
    "performance": ("performance",),
}


def _role_signals(dims: list[Dimension]) -> list[str]:
    """The roles the evidence supports: a role is claimed only when its dimensions pass."""
    passing = {d.name for d in dims if d.verdict == PASS_V}
    return [role for role, needed in _ROLE_EVIDENCE.items() if all(n in passing for n in needed)]


def _overall(dims: list[Dimension]) -> str:
    """Roll up: any fail → fail; any watchlist → watchlist; else pass. Worst wins."""
    verdicts = {d.verdict for d in dims}
    if FAIL_V in verdicts:
        return FAIL_V
    if WATCHLIST in verdicts:
        return WATCHLIST
    return PASS_V


def build_scorecard(
    path: Path,
    stage: str = "entry",
    runner: Runner = subprocess_runner,
    probe: RepoProbe | None = None,
) -> Scorecard:
    """Forge the scorecard: run the gates, read the forge signals, grade against the stage."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; choose one of {sorted(STAGES)}")
    thresholds = STAGES[stage]
    prober = probe if probe is not None else OfflineProbe()

    readings = {r.gate: r for r in diagnose(path, runner)}
    signals = prober.signals(path)

    dims: list[Dimension] = [
        _grade_gate("lint", readings["lint"]),
        _grade_gate("typecheck", readings["typecheck"]),
        _grade_tests(readings["tests"], thresholds["coverage"]),
        _grade_gate("security", readings["security"]),
        _grade_gate("dependencies", readings["dependencies"]),
        _grade_ci(signals, thresholds["workflows"]),
        _grade_collaboration(signals),
        _grade_performance(signals),
    ]

    gaps = [f"{d.name}: {d.evidence}" for d in dims if d.verdict == FAIL_V]
    gaps += [f"{d.name}: {d.evidence}" for d in dims if d.verdict == WATCHLIST]
    strengths = [d.name for d in dims if d.verdict == PASS_V]

    return Scorecard(
        repo=path.resolve().name,
        stage=stage,
        verdict=_overall(dims),
        dimensions=dims,
        role_signals=_role_signals(dims),
        top_gaps=gaps[:5],
        top_strengths=strengths,
    )
