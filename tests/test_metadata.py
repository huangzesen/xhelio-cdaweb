"""Tests for parameter metadata resolution."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cdawebmcp.metadata import (
    get_cache_dir,
    browse_parameters,
)


def test_browse_parameters_from_cache(tmp_path):
    """Test loading parameters from local metadata cache."""
    cache_dir = tmp_path / "metadata"
    cache_dir.mkdir()

    metadata = {
        "parameters": [
            {"name": "Time", "type": "isotime", "units": "UTC"},
            {"name": "BGSEc", "type": "double", "units": "nT",
             "description": "Magnetic field GSE", "size": [3]},
            {"name": "Magnitude", "type": "double", "units": "nT",
             "description": "Field magnitude"},
        ],
        "startDate": "1998-01-01",
        "stopDate": "2026-01-01",
    }
    (cache_dir / "AC_H2_MFI.json").write_text(json.dumps(metadata))

    with patch("cdawebmcp.metadata.get_cache_dir", return_value=cache_dir):
        result = browse_parameters("AC_H2_MFI")

    assert result["status"] == "success"
    assert result["dataset_id"] == "AC_H2_MFI"
    # Time parameter should be filtered out
    param_names = [p["name"] for p in result["parameters"]]
    assert "Time" not in param_names
    assert "BGSEc" in param_names
    assert "Magnitude" in param_names


def test_browse_parameters_missing_dataset(tmp_path):
    """Test that missing datasets trigger Master CDF download."""
    cache_dir = tmp_path / "metadata"
    cache_dir.mkdir()

    with patch("cdawebmcp.metadata.get_cache_dir", return_value=cache_dir):
        with patch("cdawebmcp.metadata._fetch_from_master_cdf") as mock_fetch:
            mock_fetch.return_value = {
                "parameters": [
                    {"name": "Magnitude", "type": "double", "units": "nT"},
                ],
                "startDate": "",
                "stopDate": "",
            }
            result = browse_parameters("FAKE_DATASET")

    assert result["status"] == "success"
    mock_fetch.assert_called_once()


def test_browse_parameters_includes_validation(tmp_path, monkeypatch):
    """browse_parameters should include validation status when override exists."""
    monkeypatch.setenv("CDAWEBMCP_CACHE_DIR", str(tmp_path))

    # Set up metadata cache
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    meta = {
        "parameters": [
            {"name": "Time", "type": "isotime"},
            {"name": "Magnitude", "type": "double", "units": "nT"},
        ]
    }
    (meta_dir / "AC_H2_MFI.json").write_text(json.dumps(meta))

    # Set up validation override
    override_dir = tmp_path / "overrides" / "ace"
    override_dir.mkdir(parents=True)
    override = {
        "_validated": True,
        "_validations": [
            {"version": 1, "validated_at": "2026-03-10T00:00:00",
             "discrepancies": {}, "source_file": "test.cdf"},
        ],
    }
    (override_dir / "AC_H2_MFI.json").write_text(json.dumps(override))

    # Mock the mission stem lookup
    with patch("cdawebmcp.metadata.get_cache_dir", return_value=meta_dir):
        with patch("cdawebmcp.catalog.get_mission_stem_from_dataset", return_value="ace"):
            result = browse_parameters(dataset_id="AC_H2_MFI")

    assert result["status"] == "success"
    assert result.get("validated") is True
