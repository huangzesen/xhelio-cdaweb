"""MCP server — exposes CDAWeb tools via Model Context Protocol.

Requires the [mcp] extra: pip install xhelio-cdaweb[mcp]
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Literal

import pandas as pd

try:
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:
    raise ImportError(
        "MCP server requires the 'mcp' package. "
        "Install with: pip install xhelio-cdaweb[mcp]"
    )

from cdawebmcp.catalog import browse_observatories as _browse_observatories
from cdawebmcp.config import mark_time_range_refreshed, needs_time_range_refresh
from cdawebmcp.fetch import fetch_data as _fetch_data
from cdawebmcp.metadata import browse_parameters as _browse_parameters
from cdawebmcp.prompts import build_observatory_prompt

logger = logging.getLogger(__name__)

_refresh_in_flight = False
_refresh_lock = threading.Lock()


def _make_log_fn(ctx: Context, loop: asyncio.AbstractEventLoop):
    """Create a sync log function that delegates to ctx.log() (async).

    MCP's ctx.log() is async, but library functions are sync. This wrapper
    schedules the async log call on the server's event loop without blocking.

    Args:
        ctx: MCP Context object with async log() method.
        loop: The running asyncio event loop (captured from the async tool handler).
    """
    def log_fn(level: str, message: str) -> None:
        asyncio.run_coroutine_threadsafe(ctx.log(level, message), loop)

    return log_fn


def _maybe_refresh_time_ranges(ctx: Context | None, loop: asyncio.AbstractEventLoop) -> None:
    """Refresh dataset time ranges if not done in the last 24 hours.

    Runs in a background thread so the tool call returns immediately.
    Logs progress to the MCP client via ctx.log().
    Uses a module-level flag to prevent concurrent refresh spawns.
    """
    global _refresh_in_flight
    if ctx is None or not needs_time_range_refresh():
        return

    with _refresh_lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    log_fn = _make_log_fn(ctx, loop)

    def _run():
        global _refresh_in_flight
        try:
            from cdawebmcp.cache import refresh_time_ranges
            log_fn("info", "Refreshing dataset time ranges from CDAWeb...")
            result = refresh_time_ranges()
            updated = result.get("datasets_updated", 0)
            if updated:
                log_fn("info", f"Updated time ranges for {updated} datasets")
            elif result.get("status") == "error":
                log_fn("warning", f"Time range refresh failed: {result.get('message', 'unknown error')}")
            mark_time_range_refreshed()
        except Exception as e:
            log_fn("debug", f"Time range refresh failed: {e}")
        finally:
            _refresh_in_flight = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "cdawebmcp",
        instructions="MCP server for NASA CDAWeb — browse observatories, inspect parameters, fetch heliophysics data",
    )

    @mcp.tool()
    async def browse_observatories(ctx: Context) -> str:
        """List all available CDAWeb observatories with descriptions, dataset counts, and instrument names.

        Call this first to discover what observatories are available. Returns a JSON array of observatory summaries.
        """
        loop = asyncio.get_running_loop()
        _maybe_refresh_time_ranges(ctx, loop)
        observatories = _browse_observatories()
        return json.dumps(observatories, indent=2)

    @mcp.tool()
    async def load_observatory(observatory_id: str, ctx: Context) -> str:
        """Load the complete system prompt for a CDAWeb observatory.

        Returns a detailed text prompt containing:
        - Role instructions for acting as a CDAWeb data specialist
        - CDAWeb-specific workflow (how to discover and fetch data)
        - Full dataset catalog for this observatory (instruments, dataset IDs, descriptions, time coverage)

        Use the returned text as context/instructions to work with this observatory's data.

        Args:
            observatory_id: Observatory identifier — use the lowercase stem from browse_observatories
                            (e.g., 'ace', 'parker_solar_probe_psp', 'wind', 'solar_orbiter').
        """
        loop = asyncio.get_running_loop()
        _maybe_refresh_time_ranges(ctx, loop)
        return build_observatory_prompt(observatory_id)

    @mcp.tool()
    async def browse_parameters(
        dataset_id: str,
        ctx: Context,
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
    async def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        ctx: Context,
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
        loop = asyncio.get_running_loop()
        log_fn = _make_log_fn(ctx, loop)

        # Call the library function — returns DataFrames
        lib_result = _fetch_data(
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
            log_fn=log_fn,
        )

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Filename: dataset_startdate_stopdate.format, with _1 _2 etc. if exists
        start_short = start[:10].replace("-", "")
        stop_short = stop[:10].replace("-", "")

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

        # Write to file — increment suffix if name already exists
        base_name = f"{dataset_id}_{start_short}_{stop_short}"
        file_path = out_dir / f"{base_name}.{format}"
        counter = 1
        while file_path.exists():
            file_path = out_dir / f"{base_name}_{counter}.{format}"
            counter += 1
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
    async def manage_cache(
        action: Literal["status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog"],
        ctx: Context,
        category: Literal["metadata", "cdf_cache", "all"] = "all",
        observatory: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
    ) -> str:
        """Manage the local CDAWeb cache — view status, clean files, refresh metadata, or rebuild catalogs.

        Actions:
        - "status": Show disk usage for metadata and CDF caches. Set detail=True for per-subdirectory breakdown.
        - "clean": Delete cached files. Defaults to dry_run=True (preview only). Filter by category, observatory, or age.
        - "refresh_metadata": Re-download Master CDF parameter metadata. Specify dataset_ids or observatory to scope.
        - "refresh_time_ranges": Update start/stop dates in observatory catalog JSONs from CDAWeb API. Optionally filter by observatory.
        - "rebuild_catalog": Regenerate observatory catalog JSONs from CDAWeb REST API. Optionally filter by observatory.

        Args:
            action: One of "status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog".
            category: For "clean" — "metadata", "cdf_cache", or "all" (default).
            observatory: Filter to a single observatory stem (e.g., "ace", "parker_solar_probe_psp").
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
            obs_list = [observatory] if observatory else None
            return json.dumps(
                cache_clean(
                    category=category,
                    observatories=obs_list,
                    older_than_days=older_than_days,
                    dry_run=dry_run,
                ),
                indent=2,
            )
        elif action == "refresh_metadata":
            return json.dumps(
                refresh_metadata(dataset_ids=dataset_ids, observatory=observatory),
                indent=2,
            )
        elif action == "refresh_time_ranges":
            return json.dumps(
                refresh_time_ranges(observatory=observatory),
                indent=2,
            )
        elif action == "rebuild_catalog":
            return json.dumps(
                rebuild_catalog(observatory=observatory),
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
