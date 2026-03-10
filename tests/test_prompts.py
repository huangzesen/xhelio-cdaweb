"""Tests for prompt assembly."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.prompts import build_mission_prompt


@pytest.fixture
def mock_catalog(tmp_path):
    """Set up mock mission data and prompts."""
    # Mission JSON
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()
    mission = {
        "id": "ACE",
        "name": "ACE",
        "profile": {"description": "ACE data from CDAWeb."},
        "instruments": {
            "mag": {
                "name": "Magnetic Fields",
                "keywords": ["magnetic"],
                "datasets": {
                    "AC_H2_MFI": {
                        "description": "MFI 16-sec data",
                        "start_date": "1998-01-01",
                        "stop_date": "2026-01-01",
                    }
                },
            }
        },
    }
    (missions_dir / "ace.json").write_text(json.dumps(mission))

    # Prompt templates
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "generic_role.md").write_text("You are a CDAWeb specialist.")
    (prompts_dir / "cdaweb_role.md").write_text("## CDAWeb Access\nUse browse_parameters.")

    return tmp_path


def test_build_mission_prompt(mock_catalog):
    with patch("cdawebmcp.prompts._PACKAGE_DATA", mock_catalog):
        prompt = build_mission_prompt("ace")
    assert "CDAWeb specialist" in prompt
    assert "CDAWeb Access" in prompt
    assert "AC_H2_MFI" in prompt
    assert "Dataset Catalog" in prompt


def test_build_mission_prompt_not_found(mock_catalog):
    with patch("cdawebmcp.prompts._PACKAGE_DATA", mock_catalog):
        with pytest.raises(FileNotFoundError):
            build_mission_prompt("nonexistent")
