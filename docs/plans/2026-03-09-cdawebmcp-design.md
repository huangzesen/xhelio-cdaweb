# Design: cdawebmcp — Standalone CDAWeb MCP Server

**Date:** 2026-03-09
**Status:** Draft

## Overview

`cdawebmcp` is a standalone Python package that exposes NASA's CDAWeb (Coordinated Data Analysis Web) as an MCP (Model Context Protocol) server. Any MCP-compatible LLM client can use it to discover missions, load mission-specific system prompts, browse dataset parameters, and fetch CDF data — everything needed to act as a CDAWeb data specialist.

## Motivation

xhelio's CDAWeb envoy agents are thin LLM wrappers: identical code, identical tools, differentiated only by their mission-specific system prompt. The underlying capabilities — catalog browsing, metadata lookup, data fetching — are general-purpose and useful beyond xhelio. Packaging them as an MCP server makes CDAWeb data accessible to any AI agent (Claude Desktop, Cursor, custom agents, etc.).

## MCP Tools

Four tools, forming a natural discovery funnel:

### 1. `browse_missions()`

**Purpose:** Entry point — list all available missions with descriptions.

**Parameters:** None (or optional `query: str` for keyword filtering).

**Returns:** Array of `{id, name, description, dataset_count, instruments: [str]}` — auto-generated from the bundled mission catalog JSON files.

**Source data:** Aggregated at startup from all mission JSON files in the package's `data/missions/` directory.

### 2. `load_mission(mission_id: str)`

**Purpose:** Returns the complete system prompt for a mission — role instructions, CDAWeb workflow, and full dataset catalog. Any LLM consuming this becomes a specialist for that mission.

**Parameters:**
- `mission_id` (required): Mission identifier (e.g., `"ACE"`, `"PSP"`, `"WIND"`)

**Returns:** A single text string containing the assembled prompt:
1. Generic envoy role instructions (how to use the tools, workflow patterns)
2. CDAWeb-specific instructions (fetch patterns, error handling)
3. Full mission catalog rendered as markdown (all instruments, dataset IDs, descriptions, time coverage, PI names, DOIs)

**Note:** This is the same prompt currently assembled by `knowledge/prompt_builder.py:build_envoy_prompt()` in xhelio, but self-contained in the package.

### 3. `browse_parameters(dataset_id: str)`

**Purpose:** Returns variable-level metadata for a specific dataset.

**Parameters:**
- `dataset_id` (required): CDAWeb dataset ID (e.g., `"AC_H2_MFI"`)
- `dataset_ids` (optional): Array of dataset IDs for batch lookup

**Returns:** Per-dataset parameter list with `{name, type, units, description, size}` plus time range coverage. Fetched on demand from CDAWeb Master CDF files, then cached locally.

**Side effect:** When metadata is fetched, the mission catalog's date range for that dataset is updated if CDAWeb reports newer dates.

### 4. `fetch_data(dataset_id, parameters, start, stop)`

**Purpose:** Downloads CDF data from CDAWeb, writes to a temporary file, and returns metadata.

**Parameters:**
- `dataset_id` (required): CDAWeb dataset ID
- `parameters` (required): List of parameter names to fetch
- `start` (required): Start datetime (ISO 8601)
- `stop` (required): End datetime (ISO 8601)
- `format` (optional): `"csv"` (default) or `"json"` — output file format
- `output_dir` (optional): Directory to write the output file. Defaults to system temp dir.

**Returns:** Rich metadata + file path — no inline data. The response includes:

```json
{
  "status": "success",
  "file_path": "/tmp/AC_H2_MFI_20260309_143022.csv",
  "format": "csv",
  "dataset_id": "AC_H2_MFI",
  "time_range": {"start": "2024-01-01T00:00:00", "stop": "2024-01-07T00:00:00"},
  "total_rows": 37800,
  "parameters": {
    "BGSEc": {
      "status": "success",
      "units": "nT",
      "description": "Magnetic field GSE Cartesian",
      "columns": ["BGSEc.1", "BGSEc.2", "BGSEc.3"],
      "rows": 37800,
      "stats": {
        "BGSEc.1": {"min": -12.3, "max": 15.1, "mean": 1.2, "std": 4.5, "nan_ratio": 0.02},
        "BGSEc.2": {"min": -8.7, "max": 9.2, "mean": -0.3, "std": 3.1, "nan_ratio": 0.02},
        "BGSEc.3": {"min": -6.1, "max": 7.8, "mean": 0.8, "std": 2.9, "nan_ratio": 0.02}
      }
    },
    "Magnitude": {
      "status": "success",
      "units": "nT",
      "description": "Field magnitude",
      "columns": ["Magnitude.1"],
      "rows": 37800,
      "stats": {
        "Magnitude.1": {"min": 2.1, "max": 18.3, "mean": 5.6, "std": 2.8, "nan_ratio": 0.01}
      }
    }
  }
}
```

The `stats` block gives the LLM enough information to judge data quality without reading the file:
- **`nan_ratio`** — fraction of NaN values (0.0–1.0). High ratio → bad data, skip this parameter/dataset.
- **`min/max/mean/std`** — basic descriptive statistics. Helps catch fill-value leaks, unreasonable ranges, or flat signals.
- **`rows`** — total data points. Too few → data gap, too many → consider if time range is correct.

**Why file-based:** CDAWeb datasets can be hundreds of MB. Returning data inline would bloat MCP JSON responses and force double serialization (DataFrame → JSON string → parse). Writing to disk lets consumers (xhelio, Claude Desktop, scripts) handle the data in their own way. The rich metadata summary lets the LLM make informed load/skip decisions without reading the file.

**Size guard:** Warns for requests > 500 MB estimated, rejects > 1 GB unless `force: true` is passed.

**Temp file lifecycle:** The MCP server writes the file but does NOT delete it. The caller is responsible for cleanup. In xhelio, the orchestrator cleans up session temp files at cycle end.

## Package Structure

```
cdawebmcp/
├── pyproject.toml              # Package config, entry points
├── README.md
├── src/
│   └── cdawebmcp/
│       ├── __init__.py
│       ├── __main__.py         # python -m cdawebmcp entry point
│       ├── server.py           # MCP server (FastMCP)
│       ├── catalog.py          # Mission catalog loading + aggregation
│       ├── metadata.py         # Parameter metadata (Master CDF fetch + cache)
│       ├── fetch.py            # CDF data download + conversion
│       ├── prompts.py          # Prompt assembly for load_mission
│       ├── http.py             # HTTP client with retry logic
│       ├── data/
│       │   ├── missions/       # Bundled mission JSON files (built at release)
│       │   │   ├── ace.json
│       │   │   ├── psp.json
│       │   │   ├── wind.json
│       │   │   └── ...
│       │   └── prompts/        # Prompt templates
│       │       ├── generic_role.md
│       │       └── cdaweb_role.md
│       └── scripts/
│           └── build_catalog.py  # Fetches CDAWeb API → generates mission JSONs
├── tests/
│   ├── test_catalog.py
│   ├── test_metadata.py
│   └── test_fetch.py
└── .github/
    └── workflows/
        └── update-catalog.yml  # Weekly CI job to rebuild mission JSONs
```

## Dependencies

Minimal — no xhelio dependency:

```toml
[project]
dependencies = [
    "mcp>=1.0",          # MCP SDK (FastMCP)
    "cdflib>=1.0",       # CDF file reading
    "pandas>=2.0",       # DataFrame operations
    "numpy>=1.24",       # Array operations
    "requests>=2.28",    # HTTP client for CDAWeb API
]
```

## Data Flow

```
User/LLM
  │
  ├── browse_missions()
  │     └── reads bundled data/missions/*.json → returns mission list
  │
  ├── load_mission("ACE")
  │     ├── reads data/prompts/generic_role.md
  │     ├── reads data/prompts/cdaweb_role.md
  │     ├── reads data/missions/ace.json → renders as markdown
  │     └── returns assembled system prompt
  │
  ├── browse_parameters("AC_H2_MFI")
  │     ├── checks ~/.cdawebmcp/metadata/AC_H2_MFI.json (local cache)
  │     ├── if miss → downloads Master CDF from CDAWeb, parses, caches
  │     ├── side-effect: updates ace.json date range if newer
  │     └── returns parameter list
  │
  └── fetch_data("AC_H2_MFI", ["Magnitude", "BGSEc"], "2024-01-01", "2024-01-07")
        ├── downloads CDF files from CDAWeb REST API
        ├── reads with cdflib → pandas DataFrame
        ├── writes CSV/JSON to output_dir (or system temp)
        └── returns metadata + file_path (NOT the data itself)
```

### xhelio Integration Flow

When used from xhelio, the envoy LLM controls the full workflow:

```
Envoy LLM
  │
  ├── browse_parameters("AC_H2_MFI")     → parameter metadata
  ├── fetch_data("AC_H2_MFI", [...])     → {file_path, metadata summary}
  │     ↓
  │   LLM inspects metadata — rows, columns, time range, errors
  │     ↓
  ├── if good → load_file(file_path)     → ingests into DataStore, returns data_labels
  │   if bad  → try different dataset or inform user
  └── [orchestrator cycle-end cleanup]   → deletes temp files
```

**The envoy LLM is in the loop between fetch and ingest.** `fetch_data` is a pure MCP proxy — the xhelio handler does NOT auto-ingest. The LLM sees the data summary (row count, columns, any errors) and decides whether to load it. This lets the LLM catch problems early: all-NaN data, wrong time range, unexpected column count, etc.

This follows the same pattern as the SPICE envoy: `get_ephemeris` returns metadata + file path, the envoy LLM inspects the result, then calls `load_file` to ingest.

## Catalog Build Pipeline

The mission JSON files are generated by `scripts/build_catalog.py` (extracted from xhelio's `generate_mission_data.py`):

1. Queries CDAWeb REST API (`/datasets` endpoint) for the full dataset catalog (~3000 datasets)
2. Groups datasets by observatory/mission using prefix matching
3. Categorizes into instrument groups using CDAWeb's `InstrumentType` taxonomy
4. Writes one JSON file per mission with: id, name, profile, instruments, datasets (description, dates, PI, DOI)

This runs:
- **At release time** — bundled JSONs ship with the package
- **Weekly via CI** — a GitHub Actions workflow rebuilds and commits updated JSONs
- **Manually** — `python -m cdawebmcp.scripts.build_catalog` for local rebuild

## Cache Layout

```
~/.cdawebmcp/
├── metadata/           # Parameter metadata cache (auto-populated)
│   ├── AC_H2_MFI.json
│   ├── PSP_FLD_L2_MAG_RTN_1MIN.json
│   └── ...
└── cdf_cache/          # Downloaded CDF files (optional, configurable)
    └── ...
```

Cache location configurable via `CDAWEBMCP_CACHE_DIR` env var.

## Usage

### As MCP server (stdio transport)

```json
{
  "mcpServers": {
    "cdaweb": {
      "command": "python",
      "args": ["-m", "cdawebmcp"]
    }
  }
}
```

Or with `uvx` (no install needed):

```json
{
  "mcpServers": {
    "cdaweb": {
      "command": "uvx",
      "args": ["cdawebmcp"]
    }
  }
}
```

### As Python library

```python
from cdawebmcp.catalog import browse_missions, load_mission
from cdawebmcp.metadata import browse_parameters
from cdawebmcp.fetch import fetch_data

missions = browse_missions()
prompt = load_mission("ACE")
params = browse_parameters("AC_H2_MFI")
data = fetch_data("AC_H2_MFI", ["Magnitude"], "2024-01-01", "2024-01-07")
```

## Integration with xhelio

### Architecture: One MCP, Many Envoys

Unlike SPICE (one mission = one envoy), CDAWeb is **one MCP server serving ~40+ missions**. All CDAWeb envoys share the same kind (`"cdaweb"`) and connect to the same MCP subprocess. The `browse_missions` tool is the MCP's entry point for discovery, but xhelio's envoy system already knows which missions exist (from the bundled catalog). The per-mission differentiation happens through `load_mission`, which returns the mission-specific system prompt.

**Key implication:** The xhelio CDAWeb kind module (`knowledge/envoys/cdaweb/`) manages a single shared MCP client singleton (like `knowledge/envoys/spice/client.py`), not one client per mission. All CDAWeb envoy agents route their tool calls through this shared client.

**`browse_missions` in xhelio context:** xhelio's orchestrator does NOT call `browse_missions` — it already knows the mission list from the envoy kind registry. `browse_missions` is primarily for standalone MCP consumers (Claude Desktop, other agents) that need to discover available missions. In xhelio, the equivalent is `envoy_query(action="list_envoys")`.

### Migration Plan

After `cdawebmcp` is published:

1. xhelio adds `cdawebmcp` as a dependency
2. `knowledge/envoys/cdaweb/client.py` — new file, MCP client singleton (same pattern as `spice/client.py`)
3. `knowledge/envoys/cdaweb/handlers.py` — handlers become thin MCP proxies:
   - `handle_browse_parameters` → calls MCP `browse_parameters`, returns result
   - `handle_fetch_data_cdaweb` → calls MCP `fetch_data` with `output_dir=session_tmp_dir`, returns metadata + file path. No auto-ingestion — the envoy LLM decides whether to call `load_file`.
4. `knowledge/envoys/cdaweb/__init__.py` — TOOLS schemas updated; GLOBAL_TOOLS includes `load_file` for ingestion
5. The internal `knowledge/metadata_client.py`, `data_ops/fetch_cdf.py` are no longer used by envoys (may still be used by other parts of xhelio during transition)

This is a future migration — xhelio continues working as-is until the package is ready.

## What Gets Extracted from xhelio

| xhelio module | → cdawebmcp module | Notes |
|---|---|---|
| `knowledge/envoys/cdaweb/*.json` | `data/missions/*.json` | Regenerated by build script, not copied |
| `knowledge/prompts/envoy/generic_role.md` | `data/prompts/generic_role.md` | Adapted (remove xhelio-specific refs) |
| `knowledge/prompts/envoy_cdaweb/role.md` | `data/prompts/cdaweb_role.md` | Adapted |
| `knowledge/cdaweb_metadata.py` | `catalog.py` | CDAWeb REST API client |
| `knowledge/master_cdf.py` | `metadata.py` | Master CDF download + parse |
| `knowledge/mission_prefixes.py` | `catalog.py` | Dataset → mission matching |
| `data_ops/fetch_cdf.py` | `fetch.py` | CDF download + DataFrame conversion |
| `data_ops/http_utils.py` | `http.py` | Retry logic |
| `scripts/generate_mission_data.py` | `scripts/build_catalog.py` | Catalog generation |

## Resolved Decisions

1. **Repository location:** Separate repo — `huangzesen/cdawebmcp`
2. **PPI support:** CDAWeb-only in v1. PPI can be added later.
3. **Prompt customization:** `load_mission` returns the full prompt only — no options.
4. **fetch_data returns metadata, not data.** Data is written to a temp file on disk. The caller (xhelio's `load_file`, or a standalone script) reads the file. This avoids bloating MCP responses with 100s of MB of serialized data.
5. **Temp file lifecycle:** The MCP server writes but does not delete. In xhelio, the orchestrator cleans up session temp files at cycle end.
6. **One MCP, many envoys.** All CDAWeb missions share a single MCP subprocess. `browse_missions` is for standalone consumers; xhelio already knows its mission list.
