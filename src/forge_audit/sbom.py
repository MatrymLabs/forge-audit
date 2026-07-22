"""CARD: sbom -- read and validate a repo's Software Bill of Materials (no network).

The portfolio standard names an SBOM as supply-chain evidence. But an SBOM the tool cannot
actually parse is false assurance -- worse than none. So this part does not merely note that
a file exists: it reads the committed SBOM, recognizes its format (CycloneDX or SPDX JSON),
checks it is structurally sound, and counts the components it declares. A malformed or empty
SBOM is reported as invalid with a reason, never credited as evidence. No network: it reads
only a file already in the repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Candidate SBOM filenames, most-specific first. CycloneDX and SPDX JSON are the machine formats
# a tool can validate; `cyclonedx-py` writes `sbom.cdx.json`, so recognize that too.
_SBOM_FILENAMES = (
    "sbom.cdx.json",
    "bom.cdx.json",
    "sbom.spdx.json",
    "sbom.json",
    "bom.json",
)

_MAX_SBOM_BYTES = 25 * 1024 * 1024  # a defensive cap; real SBOMs are well under this


@dataclass(frozen=True)
class SbomInfo:
    """The verdict on a repo's SBOM: which format, how many components, and whether it is sound."""

    source_file: str  # the filename it was read from
    sbom_format: str  # "CycloneDX" | "SPDX" | "unknown"
    spec_version: str  # e.g. "1.6" (CycloneDX) or "SPDX-2.3"; "" if absent
    component_count: int  # components (CycloneDX) / packages (SPDX) declared
    valid: bool  # structurally sound enough to trust as evidence
    problem: str  # why it is not valid ("" when valid)


def find_sbom(path: Path) -> Path | None:
    """The first recognized SBOM file in the repo root, or None. (SBOMs are often gitignored
    generated evidence, so a repo legitimately ships none -- that is not this part's concern.)"""
    for name in _SBOM_FILENAMES:
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def _invalid(source: str, problem: str, fmt: str = "unknown", spec: str = "") -> SbomInfo:
    return SbomInfo(source, fmt, spec, 0, False, problem)


def _validate_cyclonedx(doc: dict, source: str) -> SbomInfo:
    """A CycloneDX JSON SBOM is sound when it names a specVersion and lists >= 1 component."""
    spec = doc.get("specVersion")
    spec_str = spec if isinstance(spec, str) else ""
    components = doc.get("components")
    if not spec_str:
        return _invalid(source, "CycloneDX SBOM has no specVersion", "CycloneDX")
    if not isinstance(components, list) or not components:
        return _invalid(source, "CycloneDX SBOM lists no components", "CycloneDX", spec_str)
    return SbomInfo(source, "CycloneDX", spec_str, len(components), True, "")


def _validate_spdx(doc: dict, source: str) -> SbomInfo:
    """An SPDX JSON SBOM is sound when it names an spdxVersion and lists at least one package."""
    version = doc.get("spdxVersion")
    spec_str = version if isinstance(version, str) else ""
    packages = doc.get("packages")
    if not spec_str:
        return _invalid(source, "SPDX SBOM has no spdxVersion", "SPDX")
    if not isinstance(packages, list) or not packages:
        return _invalid(source, "SPDX SBOM lists no packages", "SPDX", spec_str)
    return SbomInfo(source, "SPDX", spec_str, len(packages), True, "")


def validate_sbom(path: Path) -> SbomInfo | None:
    """Read and validate the repo's SBOM. None when the repo ships none; otherwise an SbomInfo
    whose `valid` flag says whether it can be trusted as evidence, with a `problem` if it cannot."""
    found = find_sbom(path)
    if found is None:
        return None
    source = found.name
    try:
        if found.stat().st_size > _MAX_SBOM_BYTES:
            return _invalid(source, "SBOM file is implausibly large")
        raw = found.read_text(errors="ignore")
    except OSError as exc:
        return _invalid(source, f"SBOM file could not be read: {exc}")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return _invalid(source, "SBOM is not valid JSON")
    if not isinstance(doc, dict):
        return _invalid(source, "SBOM is not a JSON object")
    if doc.get("bomFormat") == "CycloneDX":
        return _validate_cyclonedx(doc, source)
    if "spdxVersion" in doc:
        return _validate_spdx(doc, source)
    return _invalid(source, "SBOM is neither CycloneDX nor SPDX")
