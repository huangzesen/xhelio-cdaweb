"""Prompt assembly — builds mission-specific system prompts."""

import json
from pathlib import Path

from cdawebmcp.catalog import mission_to_markdown

_PACKAGE_DATA = Path(__file__).parent / "data"


def _load_prompt_template(filename: str) -> str:
    """Load a prompt template from the package data directory."""
    filepath = _PACKAGE_DATA / "prompts" / filename
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8").strip()


def _load_mission_json_from_data(mission_stem: str) -> dict:
    """Load a mission JSON file using the module-level _PACKAGE_DATA path.

    This exists so that _PACKAGE_DATA can be patched in tests to point
    at a temporary directory for both prompts and mission JSON files.
    """
    filepath = _PACKAGE_DATA / "missions" / f"{mission_stem}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Mission file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def build_mission_prompt(mission_stem: str) -> str:
    """Build the complete system prompt for a mission.

    Assembles three layers:
    1. Generic role instructions
    2. CDAWeb-specific workflow instructions
    3. Mission profile + full dataset catalog as markdown

    Args:
        mission_stem: Lowercase mission identifier (e.g., 'ace', 'psp').

    Returns:
        Complete system prompt string.

    Raises:
        FileNotFoundError: If no mission JSON exists.
    """
    # Layer 1: Generic role
    generic_role = _load_prompt_template("generic_role.md")

    # Layer 2: CDAWeb-specific
    cdaweb_role = _load_prompt_template("cdaweb_role.md")

    # Layer 3: Mission data
    mission = _load_mission_json_from_data(mission_stem)
    profile = mission.get("profile", {})

    # Mission overview
    overview_lines = []
    name = mission.get("name", mission_stem.upper())
    overview_lines.append(f"## Mission: {name}")
    if profile.get("description"):
        overview_lines.append(profile["description"])
    coords = profile.get("coordinate_systems", [])
    if coords:
        overview_lines.append(f"- Coordinate system(s): {', '.join(coords)}")
    cadence = profile.get("typical_cadence")
    if cadence:
        overview_lines.append(f"- Typical cadence: {cadence}")
    if profile.get("data_caveats"):
        overview_lines.append("- Data caveats: " + "; ".join(profile["data_caveats"]))
    overview_lines.append("")
    mission_overview = "\n".join(overview_lines)

    # Dataset catalog
    dataset_catalog = mission_to_markdown(mission)

    # Assemble
    parts = [p for p in [generic_role, cdaweb_role, mission_overview, dataset_catalog] if p]
    return "\n\n".join(parts)
