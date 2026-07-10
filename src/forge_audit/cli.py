"""CARD: cli -- the forge-audit command: audit a repo, emit a scorecard.

    forge-audit --path ../codeforge --stage entry --format md

Emits the scorecard in one of three shapes: `human` (a terminal summary), `json` (for
machines / another tool), or `md` (a Markdown table ready to paste into a README
Evaluation section, faithful to the JSON by construction). Exit code carries the verdict
so CI can gate on it: 0 pass · 1 watchlist · 2 fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge_audit.github import GhProbe, OfflineProbe
from forge_audit.scorecard import FAIL_V, PASS_V, STAGES, Scorecard, build_scorecard

_EXIT = {PASS_V: 0, "watchlist": 1, FAIL_V: 2}

# Verdict glyphs for the Markdown view -- a scorecard reads at a glance in a README.
_GLYPH = {PASS_V: "✅", "watchlist": "🔶", FAIL_V: "❌"}


def _render_human(card: Scorecard) -> str:
    lines = [
        f"forge-audit — {card.repo} ({card.stage} stage)",
        "",
    ]
    for d in card.dimensions:
        lines.append(f"  [{d.verdict:9}] {d.name}: {d.evidence}")
    lines.append("")
    lines.append(f"  roles: {', '.join(card.role_signals) or '(none proven)'}")
    if card.top_gaps:
        lines.append("  top gaps:")
        lines += [f"    - {g}" for g in card.top_gaps]
    lines.append("")
    lines.append(f"VERDICT: {card.verdict.upper()}")
    return "\n".join(lines)


def _glyph(verdict: str) -> str:
    """A verdict rendered as `<glyph> <word>` for the Markdown table."""
    return f"{_GLYPH.get(verdict, '')} {verdict}".strip()


def render_markdown(card: Scorecard) -> str:
    """The scorecard as a Markdown table, ready to paste into a README Evaluation section.

    Built straight from the same Scorecard the JSON serializes, so the embedded table can
    never quietly drift from the machine verdict -- the drift this tool exists to prevent.
    """
    roles = " · ".join(card.role_signals) or "(none proven)"
    lines = [
        f"### forge-audit — {card.repo} ({card.stage} stage)",
        "",
        "| Dimension | Verdict | Evidence |",
        "|---|---|---|",
    ]
    for d in card.dimensions:
        lines.append(f"| {d.name} | {_glyph(d.verdict)} | {d.evidence} |")
    lines.append(f"| **overall** | **{_glyph(card.verdict)}** | role signals: {roles} |")
    return "\n".join(lines)


_RENDERERS = {
    "human": _render_human,
    "json": lambda card: json.dumps(card.to_dict(), indent=2, ensure_ascii=False),
    "md": render_markdown,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge-audit", description="Audit a repo; emit a scorecard."
    )
    parser.add_argument("--path", default=".", help="path to the target repository (default: .)")
    parser.add_argument(
        "--stage", default="entry", choices=sorted(STAGES), help="grading stage (default: entry)"
    )
    parser.add_argument(
        "--format",
        choices=sorted(_RENDERERS),
        default="human",
        help="output shape: human (default) · json · md (README-ready table)",
    )
    # Back-compat shortcut: `--json` is `--format json` (CI dogfood and older calls use it).
    parser.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="shortcut for --format json",
    )
    parser.add_argument(
        "--online", action="store_true", help="use the live `gh` probe for issue/PR signals"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.path)
    if not path.is_dir():
        print(f"forge-audit: not a directory: {path}", file=sys.stderr)
        return 2
    probe = GhProbe() if args.online else OfflineProbe()
    card = build_scorecard(path, stage=args.stage, probe=probe)
    print(_RENDERERS[args.format](card))
    return _EXIT[card.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
