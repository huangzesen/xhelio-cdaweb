"""Tests for observatory catalog loading."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.catalog import (
    get_observatories_dir,
    load_observatory_json,
    browse_observatories,
    observatory_to_markdown,
)


@pytest.fixture
def sample_observatory(tmp_path):
    """Create a minimal observatory JSON for testing."""
    observatory = {
        "id": "ACE",
        "name": "ACE",
        "profile": {
            "description": "ACE spacecraft data from CDAWeb.",
            "coordinate_systems": ["GSE", "GSM"],
            "typical_cadence": "16s",
            "data_caveats": [],
        },
        "instruments": {
            "mag": {
                "name": "Magnetic Fields",
                "keywords": ["magnetic", "field"],
                "datasets": {
                    "AC_H2_MFI": {
                        "description": "ACE MFI 16-Second Level 2 Data",
                        "start_date": "1998-01-01",
                        "stop_date": "2026-01-01",
                        "pi_name": "N. Ness",
                    }
                },
            }
        },
    }
    obs_file = tmp_path / "ace.json"
    obs_file.write_text(json.dumps(observatory))
    return tmp_path, observatory


def test_load_observatory_json(sample_observatory):
    obs_dir, expected = sample_observatory
    with patch("cdawebmcp.catalog.get_observatories_dir", return_value=obs_dir):
        result = load_observatory_json("ace")
    assert result["id"] == "ACE"
    assert "mag" in result["instruments"]


def test_browse_observatories(sample_observatory):
    obs_dir, _ = sample_observatory
    with patch("cdawebmcp.catalog.get_observatories_dir", return_value=obs_dir):
        result = browse_observatories()
    assert len(result) == 1
    assert result[0]["id"] == "ACE"
    assert result[0]["description"] == "ACE spacecraft data from CDAWeb."
    assert result[0]["dataset_count"] == 1


def test_observatory_to_markdown(sample_observatory):
    obs_dir, _ = sample_observatory
    with patch("cdawebmcp.catalog.get_observatories_dir", return_value=obs_dir):
        observatory = load_observatory_json("ace")
    md = observatory_to_markdown(observatory)
    assert "## Dataset Catalog" in md
    assert "AC_H2_MFI" in md
    assert "N. Ness" in md
