"""CARD: fleet -- audit many repos in one run, forge one combined scorecard.

A single scorecard proves one repo. A *fleet* scorecard proves the tool serves many:
point forge-audit at every repo on the ship and it grades each with `build_scorecard`,
then rolls the per-repo verdicts up into one fleet verdict (worst-wins, the same rule the
single-repo card uses across its dimensions). This is the shared, multi-consumer surface
-- platform-style tooling, not a one-repo script.

The seams are unchanged: each repo is graded through the same `Runner` and `RepoProbe`, so
the fleet suite stays offline and deterministic exactly like the single-repo one. Input is
validated loud and early -- an empty fleet or a path that is not a directory refuses the
run rather than grading a partial, misleading fleet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forge_audit.engine import Runner, subprocess_runner
from forge_audit.github import RepoProbe
from forge_audit.scorecard import (
    FAIL_V,
    PASS_V,
    WATCHLIST,
    Scorecard,
    build_scorecard,
)

# Worst-wins ordering, shared with the single-repo roll-up: any fail sinks the fleet, any
# watchlist holds it back, only an all-pass fleet passes.
_SEVERITY = {PASS_V: 0, WATCHLIST: 1, FAIL_V: 2}


@dataclass
class FleetScorecard:
    """The forged verdict on a whole fleet: every repo's card plus the rolled-up verdict."""

    stage: str
    verdict: str
    repos: list[Scorecard]

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "verdict": self.verdict,
            "repo_count": len(self.repos),
            "repos": [card.to_dict() for card in self.repos],
        }


def fleet_verdict(cards: list[Scorecard]) -> str:
    """Roll per-repo verdicts up into one: the worst repo verdict is the fleet's."""
    if not cards:
        raise ValueError("cannot grade an empty fleet")
    return max((card.verdict for card in cards), key=lambda v: _SEVERITY[v])


def _validate(paths: list[Path]) -> None:
    """Fail loud and early: refuse an empty fleet or any path that is not a directory."""
    if not paths:
        raise ValueError("no repositories given; a fleet needs at least one path")
    not_dirs = [str(p) for p in paths if not p.is_dir()]
    if not_dirs:
        raise ValueError("not a directory: " + ", ".join(not_dirs))


def build_fleet(
    paths: list[Path],
    stage: str = "entry",
    runner: Runner = subprocess_runner,
    probe: RepoProbe | None = None,
) -> FleetScorecard:
    """Grade every repo at `paths` against `stage`; forge one combined fleet scorecard."""
    _validate(paths)
    cards = [build_scorecard(path, stage=stage, runner=runner, probe=probe) for path in paths]
    return FleetScorecard(stage=stage, verdict=fleet_verdict(cards), repos=cards)
