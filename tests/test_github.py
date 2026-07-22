"""Test twin for github.py -- the RepoProbe seam (filesystem + offline, no network)."""

from __future__ import annotations

from pathlib import Path

from forge_audit.github import (
    GhProbe,
    OfflineProbe,
    count_workflows,
    detect_license,
    is_strong_copyleft,
    performance_evidence,
    readme_coverage,
    scan_dependency_licenses,
    scan_file_licenses,
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


# --- license + provenance detection (local, network-free) -----------------------

_MIT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
_APACHE = "Apache License\nVersion 2.0, January 2004"
_BSD3 = (
    "Redistribution and use in source and binary forms, with or without modification, are "
    "permitted provided that the following conditions are met:\n"
    "* Neither the name of the copyright holder nor the names of its contributors"
)
_GPL3 = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"


def test_a_mit_license_file_is_recognized(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(_MIT)
    info = detect_license(tmp_path)
    assert info.name == "MIT" and info.source_file == "LICENSE"


def test_apache_bsd_and_gpl_are_recognized_by_signature(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(_APACHE)
    assert detect_license(tmp_path).name == "Apache-2.0"
    (tmp_path / "LICENSE").write_text(_BSD3)
    assert detect_license(tmp_path).name == "BSD-3-Clause"
    (tmp_path / "COPYING").write_text(_GPL3)  # a second file present
    # LICENSE still wins by scan order, but rewrite it to GPL to prove GPL detection
    (tmp_path / "LICENSE").write_text(_GPL3)
    assert detect_license(tmp_path).name == "GPL-3.0"


def test_an_explicit_spdx_tag_wins_over_signature(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("SPDX-License-Identifier: Apache-2.0\n" + _MIT)
    assert detect_license(tmp_path).name == "Apache-2.0"


def test_no_license_file_reads_as_none(tmp_path: Path) -> None:
    info = detect_license(tmp_path)
    assert info.name is None and info.source_file == ""


def test_an_unrecognized_license_file_reads_as_unknown(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("Do whatever you feel like, honestly.\n")
    info = detect_license(tmp_path)
    assert info.name == "unknown" and info.source_file == "LICENSE"


def test_pyproject_is_the_fallback_when_no_license_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nlicense = "MIT"\n')
    info = detect_license(tmp_path)
    assert info.name == "MIT" and "pyproject" in info.source_file


def test_an_osi_classifier_is_read_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nclassifiers = ["License :: OSI Approved :: MIT License"]\n'
    )
    assert detect_license(tmp_path).name == "MIT License"


def test_a_license_table_form_is_read_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nlicense = {text = "BSD-3-Clause"}\n'
    )
    assert detect_license(tmp_path).name == "BSD-3-Clause"


def test_a_malformed_pyproject_is_not_this_checks_business(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is not = valid toml [[[\n")
    info = detect_license(tmp_path)
    assert info.name is None  # falls through to "nothing found", never raises


def test_provenance_artifacts_are_reported(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(_MIT)
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("credits\n")
    info = detect_license(tmp_path)
    assert info.provenance == ("THIRD_PARTY_NOTICES.md",)


def test_the_probe_reports_license_signals(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(_MIT)
    signals = OfflineProbe().signals(tmp_path)
    assert signals.license_name == "MIT" and signals.license_file == "LICENSE"


# --- per-file license scan (compliance depth) -----------------------------------
def test_scan_file_licenses_counts_per_file_spdx(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# SPDX-License-Identifier: MIT\nx = 1\n")
    (tmp_path / "b.py").write_text("# SPDX-License-Identifier: GPL-3.0\ny = 2\n")
    (tmp_path / "c.py").write_text("# SPDX-License-Identifier: MIT\nz = 3\n")
    (tmp_path / "d.py").write_text("no header here\n")  # not counted
    assert scan_file_licenses(tmp_path) == {"MIT": 2, "GPL-3.0": 1}


def test_scan_skips_vendored_and_build_dirs(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("# SPDX-License-Identifier: GPL-3.0\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("// SPDX-License-Identifier: GPL-3.0\n")
    (tmp_path / "real.py").write_text("# SPDX-License-Identifier: MIT\n")
    assert scan_file_licenses(tmp_path) == {"MIT": 1}  # vendored GPL is not the repo's code


def test_scan_ignores_non_source_files(tmp_path: Path) -> None:
    (tmp_path / "data.json").write_text('{"SPDX-License-Identifier": "GPL-3.0"}')
    assert scan_file_licenses(tmp_path) == {}


def test_the_probe_reports_file_licenses(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# SPDX-License-Identifier: MIT\n")
    assert OfflineProbe().signals(tmp_path).file_licenses == (("MIT", 1),)


# --- dependency (supply-chain) license scan -----------------------------------------
def _install_dist(root: Path, name: str, metadata: str) -> None:
    """Fake an installed dist by writing its dist-info METADATA into a .venv, as pip would."""
    dist = root / ".venv" / "lib" / "python3.13" / "site-packages" / f"{name}.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(metadata)


def test_is_strong_copyleft_flags_gpl_and_agpl_but_not_lgpl_or_mpl() -> None:
    assert is_strong_copyleft("GPL-3.0-or-later")
    assert is_strong_copyleft("GNU Affero General Public License v3")
    assert is_strong_copyleft("AGPL-3.0")
    # LGPL and MPL are weak/file-level copyleft: fine to depend on, must NOT be flagged
    assert not is_strong_copyleft("LGPL-3.0")
    assert not is_strong_copyleft("GNU Lesser General Public License v2 (LGPLv2)")
    assert not is_strong_copyleft("MPL-2.0")
    assert not is_strong_copyleft("MIT")


def test_scan_dependency_licenses_reads_expression_classifier_and_field(tmp_path: Path) -> None:
    _install_dist(tmp_path, "modern-1.0", "Name: modern\nLicense-Expression: MIT\n")  # SPDX wins
    _install_dist(
        tmp_path,
        "classified-2.0",
        "Name: classified\nClassifier: License :: OSI Approved :: Apache Software License\n",
    )
    _install_dist(tmp_path, "plain-3.0", "Name: plain\nLicense: BSD-3-Clause\n")
    counts = scan_dependency_licenses(tmp_path)
    assert counts == {"MIT": 1, "Apache Software License": 1, "BSD-3-Clause": 1}


def test_scan_dependency_licenses_finds_a_gpl_dependency(tmp_path: Path) -> None:
    _install_dist(tmp_path, "risky-9.9", "Name: risky\nLicense-Expression: GPL-3.0-only\n")
    counts = scan_dependency_licenses(tmp_path)
    assert any(is_strong_copyleft(lic) for lic in counts)


def test_scan_dependency_licenses_skips_unknown_and_missing_fields(tmp_path: Path) -> None:
    _install_dist(tmp_path, "murky-1.0", "Name: murky\nLicense: UNKNOWN\n")
    _install_dist(tmp_path, "bare-1.0", "Name: bare\nSummary: no license line at all\n")
    assert scan_dependency_licenses(tmp_path) == {}


def test_a_repo_with_no_venv_reports_no_dependency_licenses(tmp_path: Path) -> None:
    assert scan_dependency_licenses(tmp_path) == {}  # a bare clone: nothing to read, never faked


def test_the_probe_reports_dependency_licenses(tmp_path: Path) -> None:
    _install_dist(tmp_path, "x-1.0", "Name: x\nLicense-Expression: MIT\n")
    assert OfflineProbe().signals(tmp_path).dependency_licenses == (("MIT", 1),)


def test_the_probe_reports_a_validated_sbom(tmp_path: Path) -> None:
    import json

    (tmp_path / "sbom.cdx.json").write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "a"}]})
    )
    sbom = OfflineProbe().signals(tmp_path).sbom
    assert sbom is not None and sbom.valid and sbom.sbom_format == "CycloneDX"


def test_the_probe_reports_no_sbom_as_none(tmp_path: Path) -> None:
    assert OfflineProbe().signals(tmp_path).sbom is None
