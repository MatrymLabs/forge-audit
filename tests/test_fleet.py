"""Test twin for fleet.py -- audit many repos, roll their verdicts up into one.

Acceptance: a green fleet passes, the roll-up is worst-wins, the JSON shape is stable.
Refusal: an empty fleet and a non-directory path fail loud and early rather than grading a
partial, misleading fleet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_audit.fleet import FleetScorecard, build_fleet, fleet_verdict
from forge_audit.scorecard import FAIL_V, PASS_V, WATCHLIST, Scorecard

from .conftest import FakeProbe, FakeRunner, green


def _card(verdict: str, repo: str = "demo") -> Scorecard:
    """A minimal Scorecard carrying just the verdict the roll-up reads."""
    return Scorecard(
        repo=repo, stage="entry", verdict=verdict, dimensions=[], role_signals=[], top_gaps=[]
    )


def _repos(tmp_path: Path, *names: str) -> list[Path]:
    """Create named repo directories so each earns a distinct scorecard name."""
    dirs = []
    for name in names:
        d = tmp_path / name
        d.mkdir()
        dirs.append(d)
    return dirs


# --- acceptance -----------------------------------------------------------------
def test_a_green_fleet_passes_and_keeps_every_repo(tmp_path, signals_all_green) -> None:
    paths = _repos(tmp_path, "alpha", "beta", "gamma")
    fleet = build_fleet(
        paths, stage="entry", runner=FakeRunner(green(90)), probe=FakeProbe(signals_all_green)
    )
    assert fleet.verdict == PASS_V
    assert [c.repo for c in fleet.repos] == ["alpha", "beta", "gamma"]


def test_a_red_gate_in_any_repo_sinks_the_whole_fleet(tmp_path, signals_all_green) -> None:
    from forge_audit.engine import CommandResult

    red = green(90) | {"ruff": CommandResult(1, "E501 line too long")}
    fleet = build_fleet(
        _repos(tmp_path, "alpha", "beta"),
        stage="entry",
        runner=FakeRunner(red),
        probe=FakeProbe(signals_all_green),
    )
    assert fleet.verdict == FAIL_V


def test_fleet_verdict_is_worst_wins() -> None:
    assert fleet_verdict([_card(PASS_V), _card(PASS_V)]) == PASS_V
    assert fleet_verdict([_card(PASS_V), _card(WATCHLIST)]) == WATCHLIST
    assert fleet_verdict([_card(WATCHLIST), _card(FAIL_V)]) == FAIL_V


def test_to_dict_carries_the_stage_count_and_every_repo(tmp_path, signals_all_green) -> None:
    fleet = build_fleet(
        _repos(tmp_path, "alpha", "beta"),
        stage="intermediate",
        runner=FakeRunner(green(90)),
        probe=FakeProbe(signals_all_green),
    )
    payload = fleet.to_dict()
    assert payload["stage"] == "intermediate"
    assert payload["repo_count"] == 2
    assert {c["repo"] for c in payload["repos"]} == {"alpha", "beta"}
    assert payload["verdict"] in {PASS_V, WATCHLIST, FAIL_V}


def test_a_single_repo_fleet_is_allowed(tmp_path, signals_all_green) -> None:
    fleet = build_fleet(
        _repos(tmp_path, "solo"),
        runner=FakeRunner(green(90)),
        probe=FakeProbe(signals_all_green),
    )
    assert isinstance(fleet, FleetScorecard)
    assert fleet.verdict == PASS_V


# --- refusal --------------------------------------------------------------------
def test_an_empty_fleet_refuses_loud() -> None:
    with pytest.raises(ValueError, match="at least one path"):
        build_fleet([])


def test_a_non_directory_path_refuses_loud(tmp_path) -> None:
    good = tmp_path / "real"
    good.mkdir()
    missing = tmp_path / "ghost"
    with pytest.raises(ValueError, match="not a directory"):
        build_fleet([good, missing])


def test_fleet_verdict_refuses_an_empty_fleet() -> None:
    with pytest.raises(ValueError, match="empty fleet"):
        fleet_verdict([])
