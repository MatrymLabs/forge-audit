"""Test twin for sbom.py -- read and validate a committed SBOM (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from forge_audit.sbom import find_sbom, normalize_dist_name, validate_sbom

# --- minimal well-formed fixtures ---------------------------------------------------
_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "components": [
        {"type": "library", "name": "requests", "version": "2.32.0"},
        {"type": "library", "name": "rich", "version": "13.7.0"},
    ],
}
_SPDX = {
    "spdxVersion": "SPDX-2.3",
    "SPDXID": "SPDXRef-DOCUMENT",
    "packages": [{"name": "requests", "SPDXID": "SPDXRef-Package-requests"}],
}


def _write(root: Path, name: str, doc) -> None:
    (root / name).write_text(doc if isinstance(doc, str) else json.dumps(doc))


def test_no_sbom_file_reads_as_none(tmp_path: Path) -> None:
    assert validate_sbom(tmp_path) is None  # a repo that ships no SBOM is not this part's concern


def test_a_valid_cyclonedx_sbom_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.cdx.json", _CYCLONEDX)
    info = validate_sbom(tmp_path)
    assert info is not None and info.valid
    assert info.sbom_format == "CycloneDX" and info.spec_version == "1.6"
    assert info.component_count == 2 and info.problem == ""


def test_a_valid_spdx_sbom_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.spdx.json", _SPDX)
    info = validate_sbom(tmp_path)
    assert info is not None and info.valid
    assert info.sbom_format == "SPDX" and info.component_count == 1


def test_malformed_json_is_invalid_not_a_crash(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.json", "{ this is not json ]")
    info = validate_sbom(tmp_path)
    assert info is not None and not info.valid and "not valid JSON" in info.problem


def test_a_cyclonedx_sbom_with_no_components_is_invalid(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "sbom.cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []},
    )
    info = validate_sbom(tmp_path)
    assert info is not None and not info.valid and "no components" in info.problem


def test_a_cyclonedx_sbom_without_a_spec_version_is_invalid(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.json", {"bomFormat": "CycloneDX", "components": [{"name": "x"}]})
    info = validate_sbom(tmp_path)
    assert info is not None and not info.valid and "specVersion" in info.problem


def test_an_unrecognized_format_is_invalid(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.json", {"some": "other", "document": True})
    info = validate_sbom(tmp_path)
    assert info is not None and not info.valid and "neither CycloneDX nor SPDX" in info.problem


def test_a_non_object_json_sbom_is_invalid(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.json", [1, 2, 3])
    info = validate_sbom(tmp_path)
    assert info is not None and not info.valid and "not a JSON object" in info.problem


def test_find_sbom_prefers_the_most_specific_name(tmp_path: Path) -> None:
    _write(tmp_path, "sbom.json", _CYCLONEDX)
    _write(tmp_path, "sbom.cdx.json", _CYCLONEDX)
    found = find_sbom(tmp_path)
    assert found is not None and found.name == "sbom.cdx.json"


def test_normalize_dist_name_follows_pep503() -> None:
    assert normalize_dist_name("Typing_Extensions") == "typing-extensions"
    assert normalize_dist_name("ruamel.yaml") == "ruamel-yaml"
    assert normalize_dist_name("Flask") == "flask"


def test_a_valid_sbom_exposes_normalized_component_names(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "sbom.cdx.json",
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"name": "Requests"}, {"name": "typing_extensions"}],
        },
    )
    info = validate_sbom(tmp_path)
    assert info is not None and info.component_names == ("requests", "typing-extensions")
