"""Tests for data validation and metadata sync."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _make_mock_cdf(z_variables, var_data):
    """Create a mock CDF object with given variables.

    Args:
        z_variables: list of variable names
        var_data: dict mapping var_name to {Data_Type_Description, Dim_Sizes, attrs}
    """
    mock_cdf = MagicMock()
    info = MagicMock()
    info.zVariables = z_variables
    info.rVariables = []
    mock_cdf.cdf_info.return_value = info

    def varinq(name):
        data = var_data[name]
        result = MagicMock()
        result.Data_Type_Description = data["Data_Type_Description"]
        result.Dim_Sizes = data.get("Dim_Sizes", [])
        return result

    def varattsget(name):
        return var_data[name].get("attrs", {})

    mock_cdf.varinq.side_effect = varinq
    mock_cdf.varattsget.side_effect = varattsget
    return mock_cdf


def test_inspect_cdf_variables():
    from cdawebmcp.validation import inspect_cdf_variables

    mock_cdf = _make_mock_cdf(
        ["Epoch", "Magnitude", "BGSEc", "Quality_Flag"],
        {
            "Epoch": {"Data_Type_Description": "CDF_EPOCH", "attrs": {}},
            "Magnitude": {
                "Data_Type_Description": "CDF_REAL4",
                "Dim_Sizes": [],
                "attrs": {
                    "VAR_TYPE": "data",
                    "UNITS": "nT",
                    "CATDESC": "Magnetic field magnitude",
                },
            },
            "BGSEc": {
                "Data_Type_Description": "CDF_REAL4",
                "Dim_Sizes": [3],
                "attrs": {
                    "VAR_TYPE": "data",
                    "UNITS": "nT",
                    "CATDESC": "Magnetic field in GSE",
                },
            },
            "Quality_Flag": {
                "Data_Type_Description": "CDF_INT1",
                "Dim_Sizes": [],
                "attrs": {
                    "VAR_TYPE": "support_data",
                },
            },
        },
    )

    with patch("cdawebmcp.validation.cdflib") as mock_cdflib:
        mock_cdflib.CDF.return_value = mock_cdf
        result = inspect_cdf_variables(Path("/fake/file.cdf"))

    # Should include Magnitude and BGSEc (data vars), skip Epoch (time) and Quality_Flag (support_data)
    names = [v["name"] for v in result]
    assert "Magnitude" in names
    assert "BGSEc" in names
    assert "Epoch" not in names
    assert "Quality_Flag" not in names


# ---------------------------------------------------------------------------
# Override file read/write
# ---------------------------------------------------------------------------

from cdawebmcp.validation import load_override, save_override


def test_save_and_load_override(tmp_path, monkeypatch):
    """Override files should round-trip correctly."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    override = {
        "_validated": True,
        "_validations": [
            {
                "version": 1,
                "source_file": "ac_h2_mfi_20240101.cdf",
                "validated_at": "2026-03-10T12:00:00+00:00",
                "discrepancies": {},
            }
        ],
    }
    save_override("AC_H2_MFI", override, mission_stem="ace")

    loaded = load_override("AC_H2_MFI", mission_stem="ace")
    assert loaded is not None
    assert loaded["_validated"] is True
    assert len(loaded["_validations"]) == 1


def test_load_override_missing(tmp_path, monkeypatch):
    """load_override should return None for missing files."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)
    result = load_override("NONEXISTENT", mission_stem="fake")
    assert result is None


def test_save_override_merges(tmp_path, monkeypatch):
    """Saving an override twice should deep-merge, not overwrite."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    save_override("AC_H2_MFI", {"_validated": True, "key1": "val1"}, mission_stem="ace")
    save_override("AC_H2_MFI", {"key2": "val2"}, mission_stem="ace")

    loaded = load_override("AC_H2_MFI", mission_stem="ace")
    assert loaded["_validated"] is True
    assert loaded["key1"] == "val1"
    assert loaded["key2"] == "val2"


# ---------------------------------------------------------------------------
# sync_metadata
# ---------------------------------------------------------------------------

from cdawebmcp.validation import sync_metadata


def test_sync_metadata_detects_phantom(tmp_path, monkeypatch):
    """Parameters in metadata but not in data CDF should be marked as phantom."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    # Set up metadata cache with Magnitude and Phantom_Var
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    meta = {
        "parameters": [
            {"name": "Time", "type": "isotime"},
            {"name": "Magnitude", "type": "double", "units": "nT"},
            {"name": "Phantom_Var", "type": "double", "units": ""},
        ]
    }
    (meta_dir / "AC_H2_MFI.json").write_text(json.dumps(meta))

    # Mock CDF that has Magnitude but NOT Phantom_Var
    mock_cdf = _make_mock_cdf(
        ["Epoch", "Magnitude"],
        {
            "Epoch": {"Data_Type_Description": "CDF_EPOCH", "attrs": {}},
            "Magnitude": {
                "Data_Type_Description": "CDF_REAL4",
                "attrs": {"VAR_TYPE": "data", "UNITS": "nT", "CATDESC": "B mag"},
            },
        },
    )

    with patch("cdawebmcp.validation.cdflib") as mock_cdflib:
        mock_cdflib.CDF.return_value = mock_cdf
        sync_metadata(
            dataset_id="AC_H2_MFI",
            cdf_path=Path("/fake/data.cdf"),
            source_url="https://example.com/data.cdf",
            mission_stem="ace",
        )

    # Check override was written
    override = json.loads(
        (tmp_path / "overrides" / "ace" / "AC_H2_MFI.json").read_text()
    )
    assert override["_validated"] is True
    assert len(override["_validations"]) == 1
    discrepancies = override["_validations"][0]["discrepancies"]
    assert "Phantom_Var" in discrepancies
    assert discrepancies["Phantom_Var"]["_category"] == "phantom"


def test_sync_metadata_detects_undocumented(tmp_path, monkeypatch):
    """Parameters in data CDF but not in metadata should be marked as undocumented."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    meta = {
        "parameters": [
            {"name": "Time", "type": "isotime"},
            {"name": "Magnitude", "type": "double"},
        ]
    }
    (meta_dir / "AC_H2_MFI.json").write_text(json.dumps(meta))

    # CDF has Magnitude + an extra Secret_Var
    mock_cdf = _make_mock_cdf(
        ["Epoch", "Magnitude", "Secret_Var"],
        {
            "Epoch": {"Data_Type_Description": "CDF_EPOCH", "attrs": {}},
            "Magnitude": {
                "Data_Type_Description": "CDF_REAL4",
                "attrs": {"VAR_TYPE": "data", "UNITS": "nT", "CATDESC": "B mag"},
            },
            "Secret_Var": {
                "Data_Type_Description": "CDF_REAL4",
                "attrs": {"VAR_TYPE": "data", "UNITS": "km/s", "CATDESC": "Secret"},
            },
        },
    )

    with patch("cdawebmcp.validation.cdflib") as mock_cdflib:
        mock_cdflib.CDF.return_value = mock_cdf
        sync_metadata(
            dataset_id="AC_H2_MFI",
            cdf_path=Path("/fake/data.cdf"),
            source_url="https://example.com/data.cdf",
            mission_stem="ace",
        )

    override = json.loads(
        (tmp_path / "overrides" / "ace" / "AC_H2_MFI.json").read_text()
    )
    discrepancies = override["_validations"][0]["discrepancies"]
    assert "Secret_Var" in discrepancies
    assert discrepancies["Secret_Var"]["_category"] == "undocumented"


def test_sync_metadata_skips_already_validated(tmp_path, monkeypatch):
    """sync_metadata should skip if the same source_url was already validated."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    (meta_dir / "AC_H2_MFI.json").write_text('{"parameters": [{"name": "Time"}]}')

    # Pre-seed an override with a validation for this URL
    override_dir = tmp_path / "overrides" / "ace"
    override_dir.mkdir(parents=True)
    existing = {
        "_validated": True,
        "_validations": [
            {"version": 1, "source_url": "https://example.com/data.cdf",
             "validated_at": "2026-01-01T00:00:00", "discrepancies": {}},
        ],
    }
    (override_dir / "AC_H2_MFI.json").write_text(json.dumps(existing))

    # sync_metadata should NOT call cdflib.CDF since it's already validated
    with patch("cdawebmcp.validation.cdflib") as mock_cdflib:
        sync_metadata(
            dataset_id="AC_H2_MFI",
            cdf_path=Path("/fake/data.cdf"),
            source_url="https://example.com/data.cdf",
            mission_stem="ace",
        )
        mock_cdflib.CDF.assert_not_called()


def test_sync_metadata_appends_validation(tmp_path, monkeypatch):
    """Multiple syncs with different source URLs should append to _validations."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    meta = {"parameters": [{"name": "Time"}, {"name": "Bx", "type": "double"}]}
    (meta_dir / "AC_H2_MFI.json").write_text(json.dumps(meta))

    mock_cdf = _make_mock_cdf(
        ["Epoch", "Bx"],
        {
            "Epoch": {"Data_Type_Description": "CDF_EPOCH", "attrs": {}},
            "Bx": {
                "Data_Type_Description": "CDF_REAL4",
                "attrs": {"VAR_TYPE": "data", "UNITS": "nT", "CATDESC": "Bx"},
            },
        },
    )

    with patch("cdawebmcp.validation.cdflib") as mock_cdflib:
        mock_cdflib.CDF.return_value = mock_cdf

        sync_metadata("AC_H2_MFI", Path("/f1.cdf"), source_url="url1", mission_stem="ace")
        sync_metadata("AC_H2_MFI", Path("/f2.cdf"), source_url="url2", mission_stem="ace")

    override = json.loads(
        (tmp_path / "overrides" / "ace" / "AC_H2_MFI.json").read_text()
    )
    assert len(override["_validations"]) == 2
    assert override["_validations"][0]["version"] == 1
    assert override["_validations"][1]["version"] == 2


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

from cdawebmcp.validation import get_quality_report


def test_get_quality_report(tmp_path, monkeypatch):
    """get_quality_report should summarize discrepancies across validations."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    override_dir = tmp_path / "overrides" / "ace"
    override_dir.mkdir(parents=True)
    override = {
        "_validated": True,
        "_validations": [
            {
                "version": 1,
                "validated_at": "2026-03-10T00:00:00",
                "discrepancies": {
                    "Phantom_Var": {"_category": "phantom", "_note": "not in data"},
                    "Secret_Var": {"_category": "undocumented", "_note": "in data only"},
                },
            }
        ],
        "parameters_annotations": {
            "Phantom_Var": {"_category": "phantom", "_note": "not in data"},
            "Secret_Var": {"_category": "undocumented", "_note": "in data only"},
        },
    }
    (override_dir / "AC_H2_MFI.json").write_text(json.dumps(override))

    report = get_quality_report("AC_H2_MFI", mission_stem="ace")
    assert report is not None
    assert report["validated"] is True
    assert "Phantom_Var" in report["metadata_only"]
    assert "Secret_Var" in report["data_only"]
    assert report["validation_count"] == 1


def test_get_quality_report_no_override(tmp_path, monkeypatch):
    """get_quality_report should return None if no override exists."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)
    report = get_quality_report("NONEXISTENT", mission_stem="fake")
    assert report is None
