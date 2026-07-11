"""Test twin for cli.py -- argument parsing, JSON emission, verdict-carrying exit codes.

Every `main()` call that reaches the gates injects a FakeRunner (the same seam the engine
and scorecard tests use), so the CLI is graded offline and NEVER shells out to real tools.
That both keeps the suite fast (~28s -> <1s) and honours the repo law: tests never touch a
real tool. The two error-path tests exit before any gate runs, so they need no runner.
"""

from __future__ import annotations

import json

from forge_audit.cli import build_parser, main

from .conftest import FakeRunner, green


def _fake() -> FakeRunner:
    """A fresh all-green fake runner -- no subprocess, deterministic gate results."""
    return FakeRunner(green())


def test_a_missing_path_exits_fail(capsys) -> None:
    code = main(["--path", "/no/such/repo/xyz"])  # exits at the is_dir check, no gate runs
    assert code == 2
    assert "not a directory" in capsys.readouterr().err


def test_json_flag_emits_a_parseable_scorecard(tmp_path, capsys) -> None:
    # An empty dir: no gates configured, no CI -> the tool still emits valid JSON.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci")
    main(["--path", str(tmp_path), "--json"], runner=_fake())
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo"] == tmp_path.resolve().name
    assert payload["stage"] == "entry"
    assert "verdict" in payload


def test_human_output_shows_a_verdict(tmp_path, capsys) -> None:
    main(["--path", str(tmp_path)], runner=_fake())
    assert "VERDICT:" in capsys.readouterr().out


def test_the_parser_rejects_an_unknown_stage(capsys) -> None:
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--stage", "nope"])


def test_markdown_format_emits_a_readme_ready_table(tmp_path, capsys) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci")
    main(["--path", str(tmp_path), "--format", "md"], runner=_fake())
    out = capsys.readouterr().out
    assert "| Dimension | Verdict | Evidence |" in out
    assert "|---|---|---|" in out
    assert "| **overall** |" in out
    assert "role signals:" in out


def test_json_shortcut_still_selects_json_format(tmp_path, capsys) -> None:
    main(["--path", str(tmp_path), "--json"], runner=_fake())
    payload = json.loads(capsys.readouterr().out)  # the shortcut must still emit valid JSON
    assert "verdict" in payload


def test_default_format_is_the_human_summary(tmp_path, capsys) -> None:
    main(["--path", str(tmp_path)], runner=_fake())
    assert "VERDICT:" in capsys.readouterr().out


def test_fleet_flag_emits_a_combined_json_scorecard(tmp_path, capsys) -> None:
    for name in ("alpha", "beta"):
        (tmp_path / name / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / name / ".github" / "workflows" / "ci.yml").write_text("name: ci")
    main(["--fleet", str(tmp_path / "alpha"), str(tmp_path / "beta"), "--json"], runner=_fake())
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_count"] == 2
    assert {c["repo"] for c in payload["repos"]} == {"alpha", "beta"}
    assert "verdict" in payload


def test_fleet_flag_rejects_a_missing_path(capsys) -> None:
    code = main(["--fleet", "/no/such/repo/xyz"])  # exits at the is_dir check, no gate runs
    assert code == 2
    assert "not a directory" in capsys.readouterr().err


def test_fleet_human_is_the_default_and_shows_a_fleet_verdict(tmp_path, capsys) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    main(["--fleet", str(tmp_path / "alpha"), str(tmp_path / "beta")], runner=_fake())
    out = capsys.readouterr().out
    assert "forge-audit fleet - 2 repo(s)" in out
    assert "FLEET VERDICT:" in out


def test_fleet_markdown_shows_a_rolled_up_fleet_row(tmp_path, capsys) -> None:
    (tmp_path / "alpha").mkdir()
    main(["--fleet", str(tmp_path / "alpha"), "--format", "md"], runner=_fake())
    out = capsys.readouterr().out
    assert "| Repo | Verdict | Role signals | Top gap |" in out
    assert "| **fleet** |" in out


def test_render_markdown_glyphs_match_verdicts() -> None:
    from forge_audit.cli import render_markdown
    from forge_audit.scorecard import Dimension, Scorecard

    card = Scorecard(
        repo="demo",
        stage="entry",
        verdict="fail",
        dimensions=[Dimension("lint", "pass", "clean"), Dimension("ci", "fail", "no CI")],
        role_signals=[],
        top_gaps=["ci: no CI"],
    )
    md = render_markdown(card)
    assert "| lint | ✅ pass | clean |" in md
    assert "| ci | ❌ fail | no CI |" in md
    assert "| **overall** | **❌ fail** | role signals: (none proven) |" in md
