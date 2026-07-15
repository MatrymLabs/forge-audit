"""Micro-benchmark for forge-audit's own grading overhead.

The performance dimension forge-audit scores asks a repo to carry a benchmark; this is ours,
and it measures the honest thing: how long the tool spends grading, given the gate results.
It runs the pure path - `build_scorecard` / `build_fleet` with an injected green runner and probe,
so no gate subprocess and no network - which isolates forge-audit's own cost from the target's
gates. The takeaway a user cares about: the tool's overhead is negligible next to running ruff /
mypy / pytest on the target, so an audit's wall-clock is the target's gates, not forge-audit.

Run: `python benchmarks/grading.py` (or `make bench`). Prints a table; commits no timings.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from forge_audit.engine import CommandResult
from forge_audit.fleet import build_fleet
from forge_audit.github import RepoSignals
from forge_audit.scorecard import build_scorecard

_ITERATIONS = 200
_FLEET_SIZES = (1, 5, 20)


def _green_runner(argv: list[str], cwd: Path) -> CommandResult:
    """Every gate passes; pytest reports a coverage TOTAL line. No subprocess."""
    if argv and argv[0] == "pytest":
        return CommandResult(0, "TOTAL    100     0   95%\n1 passed")
    return CommandResult(0, "ok")


class _GreenProbe:
    """A probe that yields all-green signals, including a benchmark artifact. No network."""

    def signals(self, path: Path) -> RepoSignals:
        return RepoSignals(workflows=3, merged_prs=4, performance="benchmarks/ directory")


def _median_us(fn, iterations: int = _ITERATIONS) -> float:
    """Median wall time of `fn` over `iterations`, in microseconds."""
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1_000_000)
    return statistics.median(samples)


def main() -> None:
    here = Path(".")
    probe = _GreenProbe()

    def one_card() -> None:
        build_scorecard(here, stage="advanced", runner=_green_runner, probe=probe)

    print("forge-audit grading overhead (injected green runner + probe; no subprocess, no network)")
    print(f"  single scorecard    : {_median_us(one_card):8.1f} us (median of {_ITERATIONS})")

    for size in _FLEET_SIZES:
        paths = [here] * size

        def a_fleet(paths: list[Path] = paths) -> None:
            build_fleet(paths, stage="advanced", runner=_green_runner, probe=probe)

        per = _median_us(a_fleet, iterations=max(20, _ITERATIONS // size))
        print(f"  fleet of {size:<3} repos   : {per:8.1f} us  ({per / size:6.1f} us/repo)")

    print("Note: this is forge-audit's own cost. A real audit is dominated by the target's gates.")


if __name__ == "__main__":
    main()
