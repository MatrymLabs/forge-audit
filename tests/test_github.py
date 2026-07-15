"""Test twin for github.py -- the RepoProbe seam (filesystem + offline, no network)."""

from __future__ import annotations

from pathlib import Path

from forge_audit.github import (
    GhProbe,
    OfflineProbe,
    count_workflows,
    performance_evidence,
    readme_coverage,
)


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


# --- performance evidence (a local, network-free artifact check) ---------------


def test_a_benchmarks_directory_is_performance_evidence(tmp_path: Path) -> None:
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "tick.py").write_text("# a benchmark\n")
    assert performance_evidence(tmp_path) == "benchmarks/ directory"


def test_an_empty_benchmarks_directory_is_not_evidence(tmp_path: Path) -> None:
    (tmp_path / "benchmarks").mkdir()  # present but empty
    assert performance_evidence(tmp_path) == ""


def test_a_makefile_bench_target_is_performance_evidence(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\nbench:\n\tpython -m bench\n")
    assert performance_evidence(tmp_path) == "Makefile bench target"


def test_a_perf_report_directory_is_performance_evidence(tmp_path: Path) -> None:
    (tmp_path / "reports" / "performance").mkdir(parents=True)
    assert performance_evidence(tmp_path) == "reports/performance/"


def test_no_benchmark_artifact_is_the_empty_string(tmp_path: Path) -> None:
    assert performance_evidence(tmp_path) == ""


def test_the_probe_reports_performance_evidence(tmp_path: Path) -> None:
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "b.py").write_text("x = 1\n")
    assert OfflineProbe().signals(tmp_path).performance == "benchmarks/ directory"


# --- readme coverage (a local, network-free content check) ----------------------

_FULL_README = (
    "# My Tool\n\nA tool that does a real, described thing for real users. " + "x " * 120 + "\n\n"
    "## Install\n\n    pip install my-tool\n\n"
    "## Usage\n\n```\nmy-tool --help\n```\n\n"
    "## Test\n\n    pytest\n"
)


def test_a_complete_readme_covers_all_four_essentials(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(_FULL_README)
    assert readme_coverage(tmp_path) == ("purpose", "install", "run", "test")


def test_a_stub_readme_covers_nothing(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Foo\nTODO\n")
    assert readme_coverage(tmp_path) == ()


def test_a_partial_readme_reports_only_what_it_covers(tmp_path: Path) -> None:
    body = (
        "A genuine description of the project. " + "detail " * 40 + "\n## Install\npip install x\n"
    )
    (tmp_path / "README.md").write_text(body)
    cov = readme_coverage(tmp_path)
    assert cov is not None
    assert "purpose" in cov and "install" in cov
    assert "run" not in cov and "test" not in cov


def test_no_readme_file_is_none(tmp_path: Path) -> None:
    assert readme_coverage(tmp_path) is None


def test_the_probe_reports_readme_coverage(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(_FULL_README)
    assert OfflineProbe().signals(tmp_path).readme == ("purpose", "install", "run", "test")
