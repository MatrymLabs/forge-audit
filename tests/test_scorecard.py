"""Test twin for scorecard.py -- EvidenceLedger grading against stage thresholds."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_audit.github import RepoSignals
from forge_audit.scorecard import FAIL_V, PASS_V, WATCHLIST, build_scorecard

from .conftest import FakeProbe, FakeRunner, green

HERE = Path(".")


def _card(runner_results, signals, stage="entry"):
    return build_scorecard(
        HERE, stage=stage, runner=FakeRunner(runner_results), probe=FakeProbe(signals)
    )


def test_a_fully_green_repo_earns_pass_and_role_signals(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)
    assert card.verdict == PASS_V
    assert not card.top_gaps
    # every role's evidence passed -> all roles claimed
    assert {"testing", "security", "backend", "devops", "collaboration"} <= set(card.role_signals)


def test_coverage_below_the_stage_floor_is_watchlist_not_pass(signals_all_green) -> None:
    # 78% clears the entry floor (70) but not intermediate (80).
    entry = _card(green(78), signals_all_green, stage="entry")
    inter = _card(green(78), signals_all_green, stage="intermediate")
    assert next(d for d in entry.dimensions if d.name == "tests").verdict == PASS_V
    assert next(d for d in inter.dimensions if d.name == "tests").verdict == WATCHLIST
    assert inter.verdict == WATCHLIST


def test_a_red_gate_forces_an_overall_fail(signals_all_green) -> None:
    from forge_audit.engine import CommandResult

    broken = green(90) | {"ruff": CommandResult(1, "E501 too long")}
    card = _card(broken, signals_all_green)
    assert card.verdict == FAIL_V
    assert any("lint" in g for g in card.top_gaps)
    # testing must NOT be claimed as a role when the overall has a hard failure elsewhere?
    # lint failing removes the backend role (needs lint+typecheck).
    assert "backend" not in card.role_signals


def test_zero_workflows_fails_the_ci_dimension(signals_all_green) -> None:
    no_ci = RepoSignals(workflows=0, merged_prs=1)
    card = _card(green(90), no_ci)
    assert next(d for d in card.dimensions if d.name == "ci").verdict == FAIL_V
    assert card.verdict == FAIL_V


def test_no_merged_prs_is_a_watchlist_collaboration_signal(signals_all_green) -> None:
    solo = RepoSignals(workflows=3, merged_prs=0)
    card = _card(green(90), solo)
    collab = next(d for d in card.dimensions if d.name == "collaboration")
    assert collab.verdict == WATCHLIST
    assert "collaboration" not in card.role_signals


def test_an_unknown_stage_fails_loud(signals_all_green) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        _card(green(90), signals_all_green, stage="wizard")


def test_the_scorecard_serializes_to_json_ready_dict(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)
    d = card.to_dict()
    assert d["verdict"] == PASS_V
    assert isinstance(d["dimensions"], list)
    assert {"name", "verdict", "evidence"} <= set(d["dimensions"][0])
