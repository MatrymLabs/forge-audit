"""CARD: cli -- the forge-audit command: audit a repo, emit a scorecard.

    forge-audit --path ../codeforge --stage entry --json

Prints a machine-readable JSON scorecard (for a README Evaluation section or another
tool) or a human-readable summary. Exit code carries the verdict so CI can gate on it:
0 pass · 1 watchlist · 2 fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge_audit.github import GhProbe, OfflineProbe
from forge_audit.scorecard import FAIL_V, PASS_V, STAGES, Scorecard, build_scorecard

_EXIT = {PASS_V: 0, "watchlist": 1, FAIL_V: 2}


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge-audit", description="Audit a repo; emit a scorecard."
    )
    parser.add_argument("--path", default=".", help="path to the target repository (default: .)")
    parser.add_argument(
        "--stage", default="entry", choices=sorted(STAGES), help="grading stage (default: entry)"
    )
    parser.add_argument("--json", action="store_true", help="emit the scorecard as JSON")
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
    if args.json:
        print(json.dumps(card.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_render_human(card))
    return _EXIT[card.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
