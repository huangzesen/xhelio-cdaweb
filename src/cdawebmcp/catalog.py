"""Observatory catalog — load observatory JSONs from cache and generate summaries."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_observatories_dir() -> Path:
    """Return the path to the observatories directory (bootstrapped cache)."""
    from cdawebmcp.config import get_cache_root
    return get_cache_root() / "observatories"


def load_observatory_json(observatory_stem: str) -> dict:
    """Load an observatory JSON file by stem name (e.g., 'ace', 'parker_solar_probe_psp').

    Args:
        observatory_stem: Lowercase observatory identifier.

    Returns:
        Parsed observatory dict.

    Raises:
        FileNotFoundError: If no JSON file exists for this observatory.
    """
    filepath = get_observatories_dir() / f"{observatory_stem}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Observatory file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def browse_observatories() -> list[dict]:
    """List all available observatories with summaries.

    Returns:
        List of dicts with: id, name, description, dataset_count, instruments.
    """
    obs_dir = get_observatories_dir()
    if not obs_dir.exists():
        return []

    results = []
    for filepath in sorted(obs_dir.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                observatory = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)
            continue

        # Count datasets across all instruments
        dataset_count = sum(
            len(inst.get("datasets", {}))
            for inst in observatory.get("instruments", {}).values()
        )

        profile = observatory.get("profile", {})
        results.append({
            "id": observatory.get("id", filepath.stem.upper()),
            "name": observatory.get("name", filepath.stem),
            "description": profile.get("description", ""),
            "dataset_count": dataset_count,
            "instruments": list(observatory.get("instruments", {}).keys()),
        })

    return results


def observatory_to_markdown(observatory: dict) -> str:
    """Convert an observatory JSON dict to a readable markdown dataset catalog.

    Args:
        observatory: Full observatory dict from load_observatory_json().

    Returns:
        Markdown string with dataset catalog.
    """
    lines = ["## Dataset Catalog", ""]
    for inst_name, inst_data in sorted(observatory.get("instruments", {}).items()):
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


def get_observatory_stem_from_dataset(dataset_id: str) -> str | None:
    """Find which observatory a dataset belongs to by scanning all observatory JSONs.

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').

    Returns:
        Observatory stem (e.g., 'ace') or None.
    """
    obs_dir = get_observatories_dir()
    if not obs_dir.exists():
        return None

    for filepath in obs_dir.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                observatory = json.load(f)
            for inst in observatory.get("instruments", {}).values():
                if dataset_id in inst.get("datasets", {}):
                    return filepath.stem
        except (json.JSONDecodeError, OSError):
            continue
    return None
