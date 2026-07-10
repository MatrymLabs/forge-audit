"""CARD: github -- the GitHub-API boundary: collaboration signals behind a seam.

A repo's collaboration story (issues → PRs → merges) and its CI wiring are portfolio
evidence, but reaching them means the network. So the network is a seam: RepoProbe is a
Protocol, the real impl shells out to the `gh` CLI, and tests inject a fake. CI runs with
no token and never hits GitHub. Workflow *count* is read from the filesystem -- no network
needed -- so an offline audit still scores the CI dimension honestly.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RepoSignals:
    """The collaboration facts an audit reads from the forge (GitHub): closed loops."""

    workflows: int  # CI workflow files present
    merged_prs: int


class RepoProbe(Protocol):
    """The seam. Any prober -- live `gh`, a fixture, a fake -- answers these."""

    def signals(self, path: Path) -> RepoSignals: ...


def count_workflows(path: Path) -> int:
    """CI wiring, read locally: how many workflow files live under .github/workflows."""
    wf_dir = path / ".github" / "workflows"
    if not wf_dir.is_dir():
        return 0
    return sum(1 for p in wf_dir.iterdir() if p.suffix in (".yml", ".yaml"))


class GhProbe:
    """The production probe: workflow count from disk, issue/PR data from `gh` (network).

    If `gh` is absent or unauthenticated, the collaboration counts read zero rather than
    raising -- an offline audit still produces a scorecard, just without the network-only
    signals. The workflow count never depends on the network.
    """

    def signals(self, path: Path) -> RepoSignals:
        return RepoSignals(
            workflows=count_workflows(path),
            merged_prs=self._gh_merged_prs(path),
        )

    def _gh_merged_prs(self, path: Path) -> int:
        out = self._gh(path, ["pr", "list", "--state", "merged", "--json", "number"])
        return len(out) if out is not None else 0

    def _gh(self, path: Path, argv: list[str]) -> list | None:
        try:
            proc = subprocess.run(
                ["gh", *argv], cwd=path, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None


class OfflineProbe:
    """A network-free probe: only the filesystem workflow count, no collaboration data.
    The honest default when no token is present -- reads zero loops rather than faking any.
    """

    def signals(self, path: Path) -> RepoSignals:
        return RepoSignals(workflows=count_workflows(path), merged_prs=0)
