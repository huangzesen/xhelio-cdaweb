"""Tests for prompt assembly."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.prompts import build_observatory_prompt


@pytest.fixture
def mock_catalog(tmp_path):
    """Set up mock observatory data and prompts."""
    observatory = {
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

    # Prompt templates
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "generic_role.md").write_text("You are a CDAWeb specialist.")
    (prompts_dir / "cdaweb_role.md").write_text("## CDAWeb Access\nUse browse_parameters.")

    return tmp_path, observatory


def test_build_observatory_prompt(mock_catalog):
    prompts_dir, observatory = mock_catalog
    with patch("cdawebmcp.prompts._BUNDLED_PROMPTS", prompts_dir / "prompts"):
        with patch("cdawebmcp.prompts.load_observatory_json", return_value=observatory):
            prompt = build_observatory_prompt("ace")
    assert "CDAWeb specialist" in prompt
    assert "CDAWeb Access" in prompt
    assert "AC_H2_MFI" in prompt
    assert "Dataset Catalog" in prompt


def test_build_observatory_prompt_not_found(mock_catalog):
    prompts_dir, _ = mock_catalog
    with patch("cdawebmcp.prompts._BUNDLED_PROMPTS", prompts_dir / "prompts"):
        with patch("cdawebmcp.prompts.load_observatory_json", side_effect=FileNotFoundError("not found")):
            with pytest.raises(FileNotFoundError):
                build_observatory_prompt("nonexistent")
