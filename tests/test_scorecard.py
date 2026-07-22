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


def test_a_not_runnable_suite_is_watchlist_not_fail(signals_all_green) -> None:
    # Auditing a foreign repo without its dev env: pytest/mypy cannot import the code. The overall
    # verdict must be WATCHLIST (we could not fully grade it), never FAIL (we do not defame it).
    from forge_audit.engine import CommandResult

    results = dict(green(90))
    results["pytest"] = CommandResult(2, "ModuleNotFoundError: No module named 'trio'\n4 errors")
    results["mypy"] = CommandResult(
        1, "error: Cannot find implementation or library stub for module named 'httpx'"
    )
    card = _card(results, signals_all_green)
    assert card.verdict == WATCHLIST
    tests_dim = next(d for d in card.dimensions if d.name == "tests")
    assert tests_dim.verdict == WATCHLIST and "not graded here" in tests_dim.evidence
    # the honest gap is surfaced, not a false failure
    assert not any(d.verdict == FAIL_V for d in card.dimensions)


def test_an_incomplete_readme_is_a_watchlist_gap(signals_all_green) -> None:
    # green everywhere, but the README skips install and test: an honest watchlist naming the gaps
    thin = RepoSignals(
        workflows=3, merged_prs=4, performance="benchmarks/", readme=("purpose", "run")
    )
    card = _card(green(90), thin)
    readme = next(d for d in card.dimensions if d.name == "readme")
    assert readme.verdict == WATCHLIST
    assert "install" in readme.evidence and "test" in readme.evidence
    assert card.verdict == WATCHLIST


def test_a_missing_readme_is_a_watchlist_gap(signals_all_green) -> None:
    none_readme = RepoSignals(workflows=3, merged_prs=4, performance="benchmarks/", readme=None)
    card = _card(green(90), none_readme)
    readme = next(d for d in card.dimensions if d.name == "readme")
    assert readme.verdict == WATCHLIST and "no README" in readme.evidence


def test_a_complete_readme_earns_a_pass_and_the_documentation_role(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)  # the fixture's README covers all four
    readme = next(d for d in card.dimensions if d.name == "readme")
    assert readme.verdict == PASS_V
    assert "documentation" in card.role_signals


def test_missing_performance_evidence_is_a_watchlist_gap(signals_all_green) -> None:
    # a repo green on every gate but carrying no benchmark artifact: an honest watchlist, not a pass
    no_bench = RepoSignals(workflows=3, merged_prs=4, performance="")
    card = _card(green(90), no_bench)
    perf = next(d for d in card.dimensions if d.name == "performance")
    assert perf.verdict == WATCHLIST
    assert card.verdict == WATCHLIST
    assert any("performance" in gap for gap in card.top_gaps)


def test_a_benchmark_artifact_earns_a_performance_pass(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)  # the fixture carries a benchmarks/ artifact
    perf = next(d for d in card.dimensions if d.name == "performance")
    assert perf.verdict == PASS_V
    assert "performance" in card.role_signals


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


def test_a_recognized_license_earns_a_pass_and_the_compliance_role(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)  # the fixture declares MIT + a notices file
    lic = next(d for d in card.dimensions if d.name == "license")
    assert lic.verdict == PASS_V
    assert "MIT" in lic.evidence and "provenance" in lic.evidence
    assert "compliance" in card.role_signals


def test_a_missing_license_is_a_watchlist_gap_not_a_fail(signals_all_green) -> None:
    no_license = RepoSignals(
        workflows=3,
        merged_prs=4,
        performance="benchmarks/",
        readme=("purpose", "install", "run", "test"),
    )
    card = _card(green(90), no_license)
    lic = next(d for d in card.dimensions if d.name == "license")
    assert lic.verdict == WATCHLIST and "reuse rights unclear" in lic.evidence
    assert card.verdict == WATCHLIST  # a missing license never fails a repo, only flags it
    assert "compliance" not in card.role_signals


def test_a_present_but_unrecognized_license_is_a_watchlist(signals_all_green) -> None:
    murky = RepoSignals(
        workflows=3,
        merged_prs=4,
        performance="benchmarks/",
        readme=("purpose", "install", "run", "test"),
        license_name="unknown",
        license_file="LICENSE",
    )
    card = _card(green(90), murky)
    lic = next(d for d in card.dimensions if d.name == "license")
    assert lic.verdict == WATCHLIST and "unrecognized" in lic.evidence


def test_an_unknown_stage_fails_loud(signals_all_green) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        _card(green(90), signals_all_green, stage="wizard")


def test_the_scorecard_serializes_to_json_ready_dict(signals_all_green) -> None:
    card = _card(green(90), signals_all_green)
    d = card.to_dict()
    assert d["verdict"] == PASS_V
    assert isinstance(d["dimensions"], list)
    assert {"name", "verdict", "evidence"} <= set(d["dimensions"][0])


# --- per-file license conflict detection (compliance depth) ---------------------------
def _license_signals(license_name, file_licenses):
    return RepoSignals(
        workflows=3,
        merged_prs=4,
        performance="benchmarks/",
        readme=("purpose", "install", "run", "test"),
        license_name=license_name,
        license_file="LICENSE",
        file_licenses=file_licenses,
    )


def test_a_copyleft_file_in_a_permissive_repo_is_flagged(signals_all_green) -> None:
    card = _card(green(90), _license_signals("MIT", (("GPL-3.0", 2),)))
    lic = next(d for d in card.dimensions if d.name == "license")
    assert lic.verdict == WATCHLIST
    assert (
        "copyleft" in lic.evidence and "GPL-3.0" in lic.evidence and "contamination" in lic.evidence
    )


def test_source_files_matching_the_declared_license_still_pass(signals_all_green) -> None:
    card = _card(green(90), _license_signals("MIT", (("MIT", 40),)))
    assert next(d for d in card.dimensions if d.name == "license").verdict == PASS_V


def test_a_non_copyleft_foreign_license_is_a_watchlist(signals_all_green) -> None:
    card = _card(green(90), _license_signals("MIT", (("Apache-2.0", 1),)))
    lic = next(d for d in card.dimensions if d.name == "license")
    assert (
        lic.verdict == WATCHLIST
        and "another license" in lic.evidence
        and "Apache-2.0" in lic.evidence
    )
