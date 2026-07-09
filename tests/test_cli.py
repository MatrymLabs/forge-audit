"""Test twin for cli.py -- argument parsing, JSON emission, verdict-carrying exit codes."""

from __future__ import annotations

import json

from forge_audit.cli import build_parser, main


def test_a_missing_path_exits_fail(capsys) -> None:
    code = main(["--path", "/no/such/repo/xyz"])
    assert code == 2
    assert "not a directory" in capsys.readouterr().err


def test_json_flag_emits_a_parseable_scorecard(tmp_path, capsys) -> None:
    # An empty dir: no gates configured, no CI -> the tool still emits valid JSON.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci")
    main(["--path", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo"] == tmp_path.resolve().name
    assert payload["stage"] == "entry"
    assert "verdict" in payload


def test_human_output_shows_a_verdict(tmp_path, capsys) -> None:
    main(["--path", str(tmp_path)])
    assert "VERDICT:" in capsys.readouterr().out


def test_the_parser_rejects_an_unknown_stage(capsys) -> None:
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--stage", "nope"])
