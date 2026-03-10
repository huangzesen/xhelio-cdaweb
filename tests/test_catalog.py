"""Tests for mission catalog loading."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.catalog import (
    get_missions_dir,
    load_mission_json,
    browse_missions,
    mission_to_markdown,
)


@pytest.fixture
def sample_mission(tmp_path):
    """Create a minimal mission JSON for testing."""
    mission = {
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
    mission_file = tmp_path / "ace.json"
    mission_file.write_text(json.dumps(mission))
    return tmp_path, mission


def test_load_mission_json(sample_mission):
    missions_dir, expected = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        result = load_mission_json("ace")
    assert result["id"] == "ACE"
    assert "mag" in result["instruments"]


def test_browse_missions(sample_mission):
    missions_dir, _ = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        result = browse_missions()
    assert len(result) == 1
    assert result[0]["id"] == "ACE"
    assert result[0]["description"] == "ACE spacecraft data from CDAWeb."
    assert result[0]["dataset_count"] == 1


def test_mission_to_markdown(sample_mission):
    missions_dir, _ = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        mission = load_mission_json("ace")
    md = mission_to_markdown(mission)
    assert "## Dataset Catalog" in md
    assert "AC_H2_MFI" in md
    assert "N. Ness" in md
