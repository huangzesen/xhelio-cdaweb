"""Mission catalog — load mission JSONs from cache and generate summaries."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_missions_dir() -> Path:
    """Return the path to the missions directory (bootstrapped cache)."""
    from cdawebmcp.config import get_cache_root
    return get_cache_root() / "missions"


def load_mission_json(mission_stem: str) -> dict:
    """Load a mission JSON file by stem name (e.g., 'ace', 'psp').

    Args:
        mission_stem: Lowercase mission identifier.

    Returns:
        Parsed mission dict.

    Raises:
        FileNotFoundError: If no JSON file exists for this mission.
    """
    filepath = get_missions_dir() / f"{mission_stem}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Mission file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def browse_missions() -> list[dict]:
    """List all available missions with summaries.

    Returns:
        List of dicts with: id, name, description, dataset_count, instruments.
    """
    missions_dir = get_missions_dir()
    if not missions_dir.exists():
        return []

    results = []
    for filepath in sorted(missions_dir.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mission = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)
            continue

        # Count datasets across all instruments
        dataset_count = sum(
            len(inst.get("datasets", {}))
            for inst in mission.get("instruments", {}).values()
        )

        profile = mission.get("profile", {})
        results.append({
            "id": mission.get("id", filepath.stem.upper()),
            "name": mission.get("name", filepath.stem),
            "description": profile.get("description", ""),
            "dataset_count": dataset_count,
            "instruments": list(mission.get("instruments", {}).keys()),
        })

    return results


def mission_to_markdown(mission: dict) -> str:
    """Convert a mission JSON dict to a readable markdown dataset catalog.

    Args:
        mission: Full mission dict from load_mission_json().

    Returns:
        Markdown string with dataset catalog.
    """
    lines = ["## Dataset Catalog", ""]
    for inst_name, inst_data in sorted(mission.get("instruments", {}).items()):
        lines.append(f"### {inst_name}")
        if inst_data.get("keywords"):
            lines.append(f"Keywords: {', '.join(inst_data['keywords'])}")
        lines.append("")
        for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
            desc = ds_info.get("description", "")
            start = ds_info.get("start_date", "?")
            stop = ds_info.get("stop_date", "?")
            lines.append(f"- **{ds_id}**: {desc}")
            lines.append(f"  Coverage: {start} to {stop}")
            if ds_info.get("pi_name"):
                lines.append(f"  PI: {ds_info['pi_name']}")
            if ds_info.get("doi"):
                lines.append(f"  DOI: {ds_info['doi']}")
        lines.append("")
    return "\n".join(lines)


def get_mission_stem_from_dataset(dataset_id: str) -> str | None:
    """Find which mission a dataset belongs to by scanning all mission JSONs.

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').

    Returns:
        Mission stem (e.g., 'ace') or None.
    """
    missions_dir = get_missions_dir()
    if not missions_dir.exists():
        return None

    for filepath in missions_dir.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mission = json.load(f)
            for inst in mission.get("instruments", {}).values():
                if dataset_id in inst.get("datasets", {}):
                    return filepath.stem
        except (json.JSONDecodeError, OSError):
            continue
    return None
