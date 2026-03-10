"""MCP server — exposes CDAWeb tools via Model Context Protocol.

Requires the [mcp] extra: pip install xhelio-cdaweb[mcp]
"""

import json
import logging
from pathlib import Path

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
        dataset_id: str | None = None,
        dataset_ids: list[str] | None = None,
    ) -> str:
        """Browse all parameters (variables) for one or more CDAWeb datasets.

        Returns parameter metadata: name, type, units, description, size, fill value.
        Use this to discover what variables a dataset contains before calling fetch_data.

        Metadata is fetched on demand from CDAWeb Master CDF files and cached locally.

        Args:
            dataset_id: Single dataset ID (e.g., 'AC_H2_MFI', 'PSP_FLD_L2_MAG_RTN_1MIN').
            dataset_ids: Multiple dataset IDs to query at once.
        """
        result = _browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        format: str = "csv",
        output_dir: str | None = None,
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
            format: Output file format — 'csv' (default) or 'json'.
            output_dir: Directory for output file. Defaults to system temp dir.
        """
        import tempfile
        from datetime import datetime

        # Call the library function — returns DataFrames
        lib_result = _fetch_data(
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
        )

        out_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir())
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

    return mcp


def serve():
    """Run the MCP server (stdio transport)."""
    logging.basicConfig(level=logging.INFO)
    server = create_server()
    server.run()
