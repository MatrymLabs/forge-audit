"""Test twin for github.py -- the RepoProbe seam (filesystem + offline, no network)."""

from __future__ import annotations

from pathlib import Path

from forge_audit.github import GhProbe, OfflineProbe, count_workflows


def test_workflows_are_counted_from_disk_without_the_network(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: ci")
    (wf / "docker.yaml").write_text("name: docker")
    (wf / "notes.txt").write_text("ignored")  # non-workflow file is not counted
    assert count_workflows(tmp_path) == 2


def test_no_workflows_directory_counts_zero(tmp_path: Path) -> None:
    assert count_workflows(tmp_path) == 0


def test_offline_probe_reads_zero_collaboration_never_faked(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci")
    signals = OfflineProbe().signals(tmp_path)
    assert signals.workflows == 1
    assert signals.merged_prs == 0


def test_gh_probe_returns_zero_when_gh_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    # Force the `gh` shell-out to fail; the probe must degrade to zeros, not raise.
    def fail(*_a, **_k):
        raise FileNotFoundError("gh not installed")

    monkeypatch.setattr("subprocess.run", fail)
    signals = GhProbe().signals(tmp_path)
    assert signals == signals.__class__(workflows=0, merged_prs=0)
