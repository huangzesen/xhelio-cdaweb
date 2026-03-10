"""Tests for cache management operations."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cdawebmcp.cache import (
    cache_clean,
    cache_status,
    rebuild_catalog,
    refresh_metadata,
    refresh_time_ranges,
)


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    """Set CDAWEBMCP_CACHE_DIR to a temp directory with fake cache files."""
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)

    # Create fake metadata cache
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    (meta_dir / "AC_H2_MFI.json").write_text('{"parameters": []}')
    (meta_dir / "PSP_FLD_L2_MAG_RTN.json").write_text('{"parameters": []}')

    # Create fake CDF cache
    cdf_dir = tmp_path / "cdf_cache" / "ace" / "mfi"
    cdf_dir.mkdir(parents=True)
    (cdf_dir / "ac_h2_mfi_20240101_v01.cdf").write_bytes(b"\x00" * 1024)

    return tmp_path


# ---------------------------------------------------------------------------
# cache_status
# ---------------------------------------------------------------------------

def test_cache_status_returns_categories(fake_cache):
    result = cache_status()
    assert result["status"] == "success"
    assert "metadata" in result["categories"]
    assert "cdf_cache" in result["categories"]
    meta = result["categories"]["metadata"]
    assert meta["file_count"] == 2
    cdf = result["categories"]["cdf_cache"]
    assert cdf["file_count"] == 1
    assert cdf["total_bytes"] == 1024
    assert result["total_bytes"] == meta["total_bytes"] + cdf["total_bytes"]


def test_cache_status_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("cdawebmcp.config._cache_dir", tmp_path)
    result = cache_status()
    assert result["status"] == "success"
    assert result["total_bytes"] == 0


# ---------------------------------------------------------------------------
# cache_clean
# ---------------------------------------------------------------------------

def test_cache_clean_dry_run(fake_cache):
    """dry_run=True should report but not delete."""
    result = cache_clean(category="cdf_cache", dry_run=True)
    assert result["dry_run"] is True
    assert result["deleted_count"] == 1
    assert result["freed_bytes"] == 1024
    # File should still exist
    cdf_dir = fake_cache / "cdf_cache" / "ace" / "mfi"
    assert (cdf_dir / "ac_h2_mfi_20240101_v01.cdf").exists()


def test_cache_clean_delete(fake_cache):
    """dry_run=False should actually delete files."""
    result = cache_clean(category="metadata", dry_run=False)
    assert result["dry_run"] is False
    assert result["deleted_count"] == 2
    meta_dir = fake_cache / "metadata"
    assert len(list(meta_dir.glob("*.json"))) == 0


def test_cache_clean_older_than(fake_cache):
    """Filter by age — fresh files should not be deleted."""
    result = cache_clean(category="cdf_cache", older_than_days=1, dry_run=False)
    # Files were just created, so nothing should be deleted
    assert result["deleted_count"] == 0


# ---------------------------------------------------------------------------
# refresh_metadata
# ---------------------------------------------------------------------------

def test_refresh_metadata_for_datasets(fake_cache):
    """refresh_metadata should re-fetch and save metadata for specified datasets."""
    fake_info = {"parameters": [{"name": "Time"}, {"name": "Bx"}]}

    with patch("cdawebmcp.cache._fetch_from_master_cdf", return_value=fake_info):
        result = refresh_metadata(dataset_ids=["AC_H2_MFI"])

    assert result["status"] == "success"
    assert result["refreshed"] == 1
    # Check the file was written
    meta_file = fake_cache / "metadata" / "AC_H2_MFI.json"
    assert meta_file.exists()
    data = json.loads(meta_file.read_text())
    assert len(data["parameters"]) == 2


def test_refresh_metadata_handles_failure(fake_cache):
    """refresh_metadata should report failures gracefully."""
    with patch("cdawebmcp.cache._fetch_from_master_cdf", return_value=None):
        result = refresh_metadata(dataset_ids=["NONEXISTENT"])

    assert result["refreshed"] == 0
    assert result["failed"] == 1


# ---------------------------------------------------------------------------
# refresh_time_ranges
# ---------------------------------------------------------------------------

def test_refresh_time_ranges(tmp_path, monkeypatch):
    """refresh_time_ranges should update start/stop dates in mission JSONs."""
    # Set up a fake missions dir with one mission
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()
    mission_data = {
        "id": "ACE",
        "name": "ACE",
        "instruments": {
            "mag": {
                "datasets": {
                    "AC_H2_MFI": {
                        "description": "ACE MFI",
                        "start_date": "1998-01-01",
                        "stop_date": "2024-01-01",
                    }
                }
            }
        },
    }
    (missions_dir / "ace.json").write_text(json.dumps(mission_data))

    fake_catalog = {
        "AC_H2_MFI": {
            "start_date": "1997-09-02T00:00:00Z",
            "stop_date": "2026-03-08T23:59:59Z",
        }
    }
    with patch("cdawebmcp.cache._fetch_cdaweb_time_ranges", return_value=fake_catalog):
        with patch("cdawebmcp.cache._get_missions_dir", return_value=missions_dir):
            result = refresh_time_ranges()

    assert result["status"] == "success"
    assert result["datasets_updated"] >= 1

    # Verify the JSON was updated
    updated = json.loads((missions_dir / "ace.json").read_text())
    ds = updated["instruments"]["mag"]["datasets"]["AC_H2_MFI"]
    assert ds["stop_date"] == "2026-03-08T23:59:59Z"


# ---------------------------------------------------------------------------
# rebuild_catalog
# ---------------------------------------------------------------------------

def test_rebuild_catalog_single_mission(tmp_path):
    """rebuild_catalog should call build_catalog logic for one mission."""
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()

    fake_catalog = {
        "AC_H2_MFI": {
            "instrument": "MAG",
            "instrument_types": ["Magnetic Fields (space)"],
            "label": "ACE MFI 16-sec Level 2",
            "observatory": "ACE",
            "pi_name": "N. Ness",
            "doi": "",
            "start_date": "1998-01-01",
            "stop_date": "2026-01-01",
        }
    }

    with patch("cdawebmcp.cache._fetch_full_cdaweb_catalog", return_value=fake_catalog):
        with patch("cdawebmcp.cache._get_missions_dir", return_value=missions_dir):
            result = rebuild_catalog(mission="ace")

    assert result["status"] == "success"
    assert result["missions_rebuilt"] == 1
    assert (missions_dir / "ace.json").exists()
