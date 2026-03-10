"""Fetch Master CDF parameter metadata for all bundled mission datasets.

Downloads Master CDF skeletons from CDAWeb, extracts parameter metadata,
and saves JSON files to src/cdawebmcp/data/metadata/ for bundling with the package.

Usage:
    python -m cdawebmcp.scripts.build_metadata              # All missions
    python -m cdawebmcp.scripts.build_metadata --mission psp # One mission
    python -m cdawebmcp.scripts.build_metadata --workers 20  # Faster parallel
"""

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

# Output directory — bundled with the package
METADATA_DIR = Path(__file__).parent.parent / "data" / "metadata"
MISSIONS_DIR = Path(__file__).parent.parent / "data" / "missions"


def collect_dataset_ids(mission_filter: str | None = None) -> list[str]:
    """Collect all dataset IDs from bundled mission JSONs."""
    dataset_ids = []
    for filepath in sorted(MISSIONS_DIR.glob("*.json")):
        if mission_filter and filepath.stem != mission_filter:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mission = json.load(f)
            for inst in mission.get("instruments", {}).values():
                for ds_id in inst.get("datasets", {}):
                    dataset_ids.append(ds_id)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", filepath.name, e)
    return dataset_ids


def fetch_one(dataset_id: str) -> tuple[str, bool]:
    """Fetch metadata for a single dataset. Returns (dataset_id, success)."""
    from cdawebmcp.metadata import _fetch_from_master_cdf

    out_path = METADATA_DIR / f"{dataset_id}.json"
    if out_path.exists():
        return dataset_id, True

    try:
        info = _fetch_from_master_cdf(dataset_id)
        if info is None:
            return dataset_id, False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return dataset_id, True
    except Exception as e:
        logger.warning("Failed %s: %s", dataset_id, e)
        return dataset_id, False


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Master CDF parameter metadata for bundled datasets"
    )
    parser.add_argument(
        "--mission", type=str,
        help="Fetch only datasets for this mission (e.g., psp, ace).",
    )
    parser.add_argument(
        "--workers", type=int, default=10,
        help="Number of parallel download workers (default: 10).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even if JSON already exists.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    mission_filter = args.mission.lower() if args.mission else None
    dataset_ids = collect_dataset_ids(mission_filter)

    if not dataset_ids:
        print("No datasets found.")
        sys.exit(1)

    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.force:
        to_fetch = dataset_ids
    else:
        to_fetch = [
            ds_id for ds_id in dataset_ids
            if not (METADATA_DIR / f"{ds_id}.json").exists()
        ]

    print(f"Found {len(dataset_ids)} datasets, {len(to_fetch)} to fetch")

    if not to_fetch:
        print("All metadata already cached.")
        return

    success = 0
    failed = 0
    workers = min(args.workers, len(to_fetch))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, ds_id): ds_id for ds_id in to_fetch}
        for future in as_completed(futures):
            ds_id, ok = future.result()
            if ok:
                success += 1
            else:
                failed += 1
                print(f"  FAIL: {ds_id}")

            total_done = success + failed
            if total_done % 50 == 0:
                print(f"  Progress: {total_done}/{len(to_fetch)}")

    print(f"\nDone: {success} succeeded, {failed} failed out of {len(to_fetch)}")


if __name__ == "__main__":
    main()
