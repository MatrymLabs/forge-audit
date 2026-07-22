"""CARD: github -- the GitHub-API boundary: collaboration signals behind a seam.

A repo's collaboration story (issues → PRs → merges) and its CI wiring are portfolio
evidence, but reaching them means the network. So the network is a seam: RepoProbe is a
Protocol, the real impl shells out to the `gh` CLI, and tests inject a fake. CI runs with
no token and never hits GitHub. Workflow *count* is read from the filesystem -- no network
needed -- so an offline audit still scores the CI dimension honestly.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RepoSignals:
    """The collaboration facts an audit reads from the forge (GitHub): closed loops."""

    workflows: int  # CI workflow files present
    merged_prs: int
    performance: str = ""  # a benchmark/profiling artifact, if one is present (evidence, or "")
    readme: tuple[str, ...] | None = None  # README essentials covered; None if there is no README
    license_name: str | None = None  # detected SPDX-ish id; "unknown" if a file is present but
    # unrecognized; None if no license is declared anywhere.
    license_file: str = ""  # where the license was read from ("" if none)
    provenance: tuple[str, ...] = ()  # third-party-notices / attribution / SBOM artifacts present
    file_licenses: tuple[tuple[str, int], ...] = ()  # per-file SPDX declarations: (spdx_id, count)
    # installed dependency licenses, from .venv dist-info: (license_string, dep_count)
    dependency_licenses: tuple[tuple[str, int], ...] = ()


class RepoProbe(Protocol):
    """The seam. Any prober -- live `gh`, a fixture, a fake -- answers these."""

    def signals(self, path: Path) -> RepoSignals: ...


def count_workflows(path: Path) -> int:
    """CI wiring, read locally: how many workflow files live under .github/workflows."""
    wf_dir = path / ".github" / "workflows"
    if not wf_dir.is_dir():
        return 0
    return sum(1 for p in wf_dir.iterdir() if p.suffix in (".yml", ".yaml"))


_BENCH_TARGET_RE = re.compile(r"^(bench|benchmark)s?\s*:", re.MULTILINE)


def performance_evidence(path: Path) -> str:
    """A benchmark/profiling artifact, read locally (no network). Returns a short evidence
    string, or "" if none is found. Objective signals - any one of:
      - a `benchmarks/` or `bench/` directory holding at least one file;
      - a `bench`/`benchmark` target in the Makefile;
      - a perf/benchmark report directory under `reports/`.

    Presence, not depth: this proves the repo carries performance evidence at all, which the
    portfolio standard calls a scored dimension. It never runs the benchmark.
    """
    for name in ("benchmarks", "bench"):
        directory = path / name
        if directory.is_dir() and any(directory.iterdir()):
            return f"{name}/ directory"
    makefile = path / "Makefile"
    if makefile.is_file() and _BENCH_TARGET_RE.search(makefile.read_text(errors="ignore")):
        return "Makefile bench target"
    reports = path / "reports"
    if reports.is_dir():
        for sub in sorted(reports.iterdir()):
            if sub.is_dir() and any(k in sub.name.lower() for k in ("perf", "bench")):
                return f"reports/{sub.name}/"
    return ""


README_ESSENTIALS = ("purpose", "install", "run", "test")
_README_NAMES = ("README.md", "README.rst", "README.txt", "README")


def readme_coverage(path: Path) -> tuple[str, ...] | None:
    """Which README essentials the target's README covers -- purpose, install, run, test -- read
    locally (no network). None if there is no README at all; otherwise a tuple (possibly empty) of
    the essentials found. The portfolio standard names a complete README a presentation gate.

    Objective, content-based signals (not vibes):
      - purpose: a real description (>= 200 non-space chars), not a stub;
      - install: an install section or a pip/poetry/npm/uv install command;
      - run:     a usage/run/quick-start/example section, or a fenced code block showing how;
      - test:    a test section or a test command (pytest, make test/check, npm test, tox).
    """
    text = ""
    for name in _README_NAMES:
        candidate = path / name
        if candidate.is_file():
            text = candidate.read_text(errors="ignore")
            break
    else:
        return None  # no README file at all
    low = text.lower()
    covered: list[str] = []
    if len(text.replace(" ", "").replace("\n", "")) >= 200:
        covered.append("purpose")
    if any(k in low for k in ("install", "poetry add", "npm install", "uv add", "getting started")):
        covered.append("install")
    if "```" in text or any(
        k in low for k in ("## usage", "## run", "quick start", "quickstart", "example", "how to")
    ):
        covered.append("run")
    if any(
        k in low
        for k in ("pytest", "make test", "make check", "npm test", "unittest", "tox", "## test")
    ):
        covered.append("test")
    return tuple(covered)


# --- license + provenance (read locally, no network) -----------------------------
_LICENSE_FILES = (
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENCE",
    "LICENCE.md",
    "COPYING",
    "COPYING.md",
)
_PROVENANCE_FILES = (
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_NOTICES",
    "NOTICE",
    "NOTICE.md",
    "ATTRIBUTION.md",
    "sbom.json",
    "bom.json",
)
_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)")
# Ordered signatures: the FIRST whose needles are all present wins, so more specific licenses
# come before the family they extend (BSD-3 before BSD-2; AGPL before GPL; GPL-3 before GPL-2).
_LICENSE_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("BSD-3-Clause", ("redistribution and use in source and binary", "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary",)),
    ("AGPL-3.0", ("gnu affero general public license",)),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("GPL-2.0", ("gnu general public license", "version 2")),
    ("LGPL-3.0", ("gnu lesser general public license",)),
    ("MPL-2.0", ("mozilla public license", "2.0")),
    ("ISC", ("isc license",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
)

# SPDX ids whose obligations are copyleft. A copyleft-licensed file inside a permissively-licensed
# repo is a real contamination signal: its terms can bind the whole distribution.
COPYLEFT_LICENSES = frozenset(
    {
        "GPL-2.0",
        "GPL-3.0",
        "GPL-2.0-only",
        "GPL-3.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-or-later",
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "LGPL-2.1",
        "LGPL-3.0",
        "LGPL-2.1-only",
        "LGPL-3.0-only",
        "MPL-2.0",
        "EPL-2.0",
        "CDDL-1.0",
    }
)

# The per-file license scan skips vendored / build / VCS trees, reads only a file's head (an SPDX
# header lives at the top), and caps the walk so a giant repo cannot stall the audit.
_SCAN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "vendor",
        "vendored",
        "third_party",
        "dist",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "site-packages",
        ".eggs",
    }
)
_SCAN_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".hpp",
        ".cc",
        ".cpp",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".sh",
        ".css",
        ".scss",
    }
)
_SCAN_MAX_FILES = 5000
_SCAN_HEAD_BYTES = 4096


def scan_file_licenses(path: Path) -> dict[str, int]:
    """Count per-file `SPDX-License-Identifier` declarations across source files (no network).
    Returns {spdx_id: file_count}; files with no SPDX header are not counted.

    This is what turns license *detection* into license *compliance*: a GPL-tagged file inside an
    MIT repo (vendored code, a copy-pasted snippet) is a real legal risk the root LICENSE hides."""
    counts: dict[str, int] = {}
    scanned = 0
    for candidate in path.rglob("*"):
        if scanned >= _SCAN_MAX_FILES:
            break
        if candidate.suffix not in _SCAN_EXTS or not candidate.is_file():
            continue
        if any(part in _SCAN_SKIP_DIRS for part in candidate.parts):
            continue
        scanned += 1
        try:
            head = candidate.read_text(errors="ignore")[:_SCAN_HEAD_BYTES]
        except OSError:
            continue
        match = _SPDX_RE.search(head)
        if match:
            spdx = match.group(1)
            counts[spdx] = counts.get(spdx, 0) + 1
    return counts


def is_strong_copyleft(license_str: str) -> bool:
    """Does this license string name STRONG (GPL/AGPL) copyleft? A strong-copyleft *dependency* can
    bind a whole distribution, a real supply-chain obligation. LGPL and MPL are deliberately left
    out: they are weak / file-level copyleft, generally fine to depend on in a permissive project,
    so flagging them would be a false alarm."""
    low = license_str.lower()
    if "lgpl" in low or "lesser" in low:
        return False
    return "gpl" in low or "affero" in low


def _dist_license(metadata: str) -> str | None:
    """The declared license of an installed dist, from its dist-info METADATA: a modern
    `License-Expression:` (SPDX) wins, then an OSI `Classifier:`, then the free-text `License:`."""
    expr = re.search(r"^License-Expression:\s*(.+)$", metadata, re.MULTILINE)
    if expr:
        return expr.group(1).strip()
    classifier = re.search(r"^Classifier: License :: OSI Approved :: (.+)$", metadata, re.MULTILINE)
    if classifier:
        return classifier.group(1).strip()
    plain = re.search(r"^License:\s*(.+)$", metadata, re.MULTILINE)
    if plain and plain.group(1).strip().upper() != "UNKNOWN":
        return plain.group(1).strip()
    return None


def scan_dependency_licenses(path: Path) -> dict[str, int]:
    """Count the declared license of each INSTALLED dependency, read from the target's own
    `.venv/**/site-packages/*.dist-info/METADATA` (no network). Returns {license_string: dep_count}.

    This is supply-chain license compliance: a GPL/AGPL dependency inside a permissive project is a
    real distribution obligation the root LICENSE says nothing about. A foreign repo we only cloned
    has no .venv, so this simply reports nothing (never a fabrication)."""
    counts: dict[str, int] = {}
    scanned = 0
    for metadata in path.glob(".venv/lib/*/site-packages/*.dist-info/METADATA"):
        if scanned >= _SCAN_MAX_FILES:
            break
        scanned += 1
        try:
            declared = _dist_license(metadata.read_text(errors="ignore")[: _SCAN_HEAD_BYTES * 2])
        except OSError:
            continue
        if declared:
            counts[declared] = counts.get(declared, 0) + 1
    return counts


@dataclass(frozen=True)
class LicenseInfo:
    """What a repo's license situation looks like, read from the filesystem only."""

    name: str | None  # SPDX-ish id, "unknown" (file present, unrecognized), or None (nothing found)
    source_file: str  # the file the name was read from, or ""
    provenance: tuple[str, ...]  # third-party-notices / attribution / SBOM artifacts present


def _identify_license_text(text: str) -> str | None:
    """Name the license in a block of text: an explicit SPDX tag wins, else a signature match,
    else None (present but unrecognized)."""
    spdx = _SPDX_RE.search(text)
    if spdx:
        return spdx.group(1)
    low = text.lower()
    for name, needles in _LICENSE_SIGNATURES:
        if all(needle in low for needle in needles):
            return name
    return None


def _license_declared_in_pyproject(path: Path) -> str | None:
    """A license DECLARED in pyproject.toml (a `[project].license` string/table, or an OSI
    classifier), used only as a fallback when no LICENSE file is present. None if not declared
    or the file is unparseable (a malformed pyproject is not this check's business)."""
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(errors="ignore"))
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    project = data.get("project", {})
    if not isinstance(project, dict):
        return None
    lic = project.get("license")
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    if isinstance(lic, dict) and isinstance(lic.get("text"), str) and lic["text"].strip():
        return lic["text"].strip()
    for classifier in project.get("classifiers", []):
        if isinstance(classifier, str) and classifier.startswith("License :: OSI Approved ::"):
            return classifier.split("::")[-1].strip()
    return None


def detect_license(path: Path) -> LicenseInfo:
    """Read a repo's license + provenance from disk (no network). A LICENSE file is the primary
    signal (typed by SPDX tag or text signature); a pyproject declaration is the fallback. A
    missing license reads as name=None -- a real gap (reuse rights unclear), never a fabrication."""
    provenance = tuple(name for name in _PROVENANCE_FILES if (path / name).is_file())
    for filename in _LICENSE_FILES:
        candidate = path / filename
        if candidate.is_file():
            name = _identify_license_text(candidate.read_text(errors="ignore")) or "unknown"
            return LicenseInfo(name=name, source_file=filename, provenance=provenance)
    declared = _license_declared_in_pyproject(path)
    if declared:
        return LicenseInfo(
            name=declared, source_file="pyproject.toml (declared)", provenance=provenance
        )
    return LicenseInfo(name=None, source_file="", provenance=provenance)


class GhProbe:
    """The production probe: workflow count from disk, issue/PR data from `gh` (network).

    If `gh` is absent or unauthenticated, the collaboration counts read zero rather than
    raising -- an offline audit still produces a scorecard, just without the network-only
    signals. The workflow count never depends on the network.
    """

    def signals(self, path: Path) -> RepoSignals:
        lic = detect_license(path)
        return RepoSignals(
            workflows=count_workflows(path),
            merged_prs=self._gh_merged_prs(path),
            performance=performance_evidence(path),
            readme=readme_coverage(path),
            license_name=lic.name,
            license_file=lic.source_file,
            provenance=lic.provenance,
            file_licenses=tuple(sorted(scan_file_licenses(path).items())),
            dependency_licenses=tuple(sorted(scan_dependency_licenses(path).items())),
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
        lic = detect_license(path)
        return RepoSignals(
            workflows=count_workflows(path),
            merged_prs=0,
            performance=performance_evidence(path),
            readme=readme_coverage(path),
            license_name=lic.name,
            license_file=lic.source_file,
            provenance=lic.provenance,
            file_licenses=tuple(sorted(scan_file_licenses(path).items())),
            dependency_licenses=tuple(sorted(scan_dependency_licenses(path).items())),
        )
