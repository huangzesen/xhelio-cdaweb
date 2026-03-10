"""MCP server — exposes CDAWeb tools via Model Context Protocol.

Requires the [mcp] extra: pip install xhelio-cdaweb[mcp]
"""

import json
import logging
from pathlib import Path
from typing import Literal

import pandas as pd

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP server requires the 'mcp' package. "
        "Install with: pip install xhelio-cdaweb[mcp]"
    )

from cdawebmcp.catalog import browse_missions as _browse_missions
from cdawebmcp.prompts import build_mission_prompt
from cdawebmcp.metadata import browse_parameters as _browse_parameters
from cdawebmcp.fetch import fetch_data as _fetch_data

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "cdawebmcp",
        instructions="MCP server for NASA CDAWeb — browse missions, inspect parameters, fetch heliophysics data",
    )

    @mcp.tool()
    def browse_missions() -> str:
        """List all available CDAWeb missions with descriptions, dataset counts, and instrument names.

        Call this first to discover what missions are available. Returns a JSON array of mission summaries.
        """
        missions = _browse_missions()
        return json.dumps(missions, indent=2)

    @mcp.tool()
    def load_mission(mission_id: str) -> str:
        """Load the complete system prompt for a CDAWeb mission.

        Returns a detailed text prompt containing:
        - Role instructions for acting as a CDAWeb data specialist
        - CDAWeb-specific workflow (how to discover and fetch data)
        - Full dataset catalog for this mission (instruments, dataset IDs, descriptions, time coverage)

        Use the returned text as context/instructions to work with this mission's data.

        Args:
            mission_id: Mission identifier — use the lowercase stem from browse_missions
                        (e.g., 'ace', 'psp', 'wind', 'solo').
        """
        return build_mission_prompt(mission_id)

    @mcp.tool()
    def browse_parameters(
        dataset_id: str,
        dataset_ids: list[str] | None = None,
    ) -> str:
        """Browse all parameters (variables) for one or more CDAWeb datasets.

        Returns parameter metadata: name, type, units, description, size, fill value.
        Use this to discover what variables a dataset contains before calling fetch_data.

        Metadata is fetched on demand from CDAWeb Master CDF files and cached locally.

        Args:
            dataset_id: Dataset ID (e.g., 'AC_H2_MFI', 'PSP_FLD_L2_MAG_RTN_1MIN').
            dataset_ids: Additional dataset IDs to query at once (batched with dataset_id).
        """
        all_ids = [dataset_id]
        if dataset_ids:
            all_ids.extend(dataset_ids)
        if len(all_ids) == 1:
            result = _browse_parameters(dataset_id=all_ids[0])
        else:
            result = _browse_parameters(dataset_ids=all_ids)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Fetch timeseries data from CDAWeb, write to a file, return metadata + stats.

        Downloads CDF files from NASA CDAWeb, extracts the requested parameters,
        writes the data to a file on disk, and returns rich metadata including
        per-column statistics (min, max, mean, std, nan_ratio).

        The data is NOT returned inline — read the file at the returned path.
        The caller is responsible for cleaning up the file when done.

        Args:
            dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').
            parameters: List of parameter names to fetch (e.g., ['BGSEc', 'Magnitude']).
            start: Start time in ISO 8601 format (e.g., '2024-01-01').
            stop: End time in ISO 8601 format (e.g., '2024-01-07').
            output_dir: Directory for the output file. Must be provided.
            format: Output file format — 'csv' (default) or 'json'.
        """
        from datetime import datetime

        # Call the library function — returns DataFrames
        lib_result = _fetch_data(
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
        )

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Merge all parameter DataFrames and write to file
        frames = []
        param_meta = {}
        for param_id, entry in lib_result.items():
            if "error" in entry:
                param_meta[param_id] = {"status": "error", "message": entry["error"]}
                continue
            df = entry["data"]
            df.columns = [f"{param_id}.{c}" for c in df.columns]
            frames.append(df)
            param_meta[param_id] = {
                "status": "success",
                "units": entry["units"],
                "description": entry["description"],
                "rows": len(df),
                "columns": list(df.columns),
                "stats": entry["stats"],
            }

        if not frames:
            return json.dumps({"status": "error", "message": "No data fetched",
                               "parameters": param_meta}, indent=2)

        merged = frames[0]
        for f in frames[1:]:
            merged = merged.join(f, how="outer")

        # Write to file
        file_path = out_dir / f"{dataset_id}_{suffix}.{format}"
        if format == "json":
            data = {"time": merged.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
            for col in merged.columns:
                data[col] = [None if pd.isna(v) else v for v in merged[col].tolist()]
            with open(file_path, "w") as f:
                json.dump(data, f)
        else:
            merged.to_csv(file_path)

        return json.dumps({
            "status": "success",
            "file_path": str(file_path),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        }, indent=2, default=str)

    @mcp.tool()
    def manage_cache(
        action: Literal["status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog"],
        category: Literal["metadata", "cdf_cache", "all"] = "all",
        mission: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
    ) -> str:
        """Manage the local CDAWeb cache — view status, clean files, refresh metadata, or rebuild catalogs.

        Actions:
        - "status": Show disk usage for metadata and CDF caches. Set detail=True for per-subdirectory breakdown.
        - "clean": Delete cached files. Defaults to dry_run=True (preview only). Filter by category, mission, or age.
        - "refresh_metadata": Re-download Master CDF parameter metadata. Specify dataset_ids or mission to scope.
        - "refresh_time_ranges": Update start/stop dates in mission catalog JSONs from CDAWeb API. Optionally filter by mission.
        - "rebuild_catalog": Regenerate mission catalog JSONs from CDAWeb REST API. Optionally filter by mission.

        Args:
            action: One of "status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog".
            category: For "clean" — "metadata", "cdf_cache", or "all" (default).
            mission: Filter to a single mission stem (e.g., "ace", "psp").
            dataset_ids: For "refresh_metadata" — specific dataset IDs to refresh.
            older_than_days: For "clean" — only delete files older than N days.
            dry_run: For "clean" — if True (default), preview without deleting.
            detail: For "status" — if True, include per-subdirectory breakdown.
        """
        from cdawebmcp.cache import (
            cache_status,
            cache_clean,
            refresh_metadata,
            refresh_time_ranges,
            rebuild_catalog,
        )

        if action == "status":
            return json.dumps(cache_status(detail=detail), indent=2)
        elif action == "clean":
            missions_list = [mission] if mission else None
            return json.dumps(
                cache_clean(
                    category=category,
                    missions=missions_list,
                    older_than_days=older_than_days,
                    dry_run=dry_run,
                ),
                indent=2,
            )
        elif action == "refresh_metadata":
            return json.dumps(
                refresh_metadata(dataset_ids=dataset_ids, mission=mission),
                indent=2,
            )
        elif action == "refresh_time_ranges":
            return json.dumps(
                refresh_time_ranges(mission=mission),
                indent=2,
            )
        elif action == "rebuild_catalog":
            return json.dumps(
                rebuild_catalog(mission=mission),
                indent=2,
            )
        else:
            return json.dumps({
                "status": "error",
                "message": f"Unknown action: {action}. "
                           "Valid: status, clean, refresh_metadata, refresh_time_ranges, rebuild_catalog",
            })

    return mcp


def serve():
    """Run the MCP server (stdio transport)."""
    import argparse

    parser = argparse.ArgumentParser(description="CDAWeb MCP server")
    parser.add_argument(
        "--cache-dir", type=str, default=None,
        help="Root directory for all caches (default: ~/.cdawebmcp/)",
    )
    args = parser.parse_args()

    if args.cache_dir:
        from cdawebmcp.config import configure
        configure(cache_dir=args.cache_dir)

    logging.basicConfig(level=logging.INFO)
    server = create_server()
    server.run()
