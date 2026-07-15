"""Shared fakes for forge-audit tests: a Runner and a RepoProbe that never touch reality.

The engine's Runner and github's RepoProbe are the two seams to the outside world. Here
they become in-memory fakes so the suite runs offline, deterministically, with no tool,
shell, or network dependency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_audit.engine import CommandResult
from forge_audit.github import RepoSignals


class FakeRunner:
    """Return canned (code, output) keyed by the tool name (argv[0])."""

    def __init__(self, results: dict[str, CommandResult]) -> None:
        self._results = results

    def __call__(self, argv: list[str], cwd: Path) -> CommandResult:
        return self._results.get(argv[0], CommandResult(0, "ok"))


class FakeProbe:
    """A RepoProbe that yields fixed signals -- no network."""

    def __init__(self, signals: RepoSignals) -> None:
        self._signals = signals

    def signals(self, path: Path) -> RepoSignals:
        return self._signals


def green(coverage: int = 90) -> dict[str, CommandResult]:
    """A canned all-green tool set: every gate passes, pytest reports `coverage`%."""
    cov_line = f"TOTAL    100     0   {coverage}%"
    return {
        "ruff": CommandResult(0, "All checks passed!"),
        "mypy": CommandResult(0, "Success: no issues found"),
        "pytest": CommandResult(0, f"{cov_line}\n1 passed"),
        "bandit": CommandResult(0, "No issues identified."),
        "pip-audit": CommandResult(0, "No known vulnerabilities found"),
    }


@pytest.fixture
def signals_all_green() -> RepoSignals:
    return RepoSignals(workflows=3, merged_prs=4, performance="benchmarks/ directory")
