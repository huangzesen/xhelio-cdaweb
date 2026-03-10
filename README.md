# xhelio-cdaweb

NASA CDAWeb data access for heliophysics — browse missions, inspect parameters, fetch CDF data.

Works as a standalone Python library or as an MCP server for any MCP-compatible LLM client (Claude Desktop, Cursor, custom agents).

## What's included

- **54 mission catalogs** with 2500+ datasets — ACE, Parker Solar Probe, Solar Orbiter, Wind, MMS, THEMIS, GOES, Voyager, and more
- **2541 pre-built parameter metadata files** from Master CDF skeletons — `browse_parameters` works instantly, no network required
- **Automatic data validation** — fetched CDF files are compared against Master CDF metadata to detect phantom (documented but missing) and undocumented (present but undocumented) parameters
- **Structured system prompts** per mission — give an LLM full context about available instruments, datasets, and time coverage

## Installation

```bash
# Library only
pip install xhelio-cdaweb

# With MCP server
pip install xhelio-cdaweb[mcp]
```

## MCP Server

### Configuration (Claude Desktop, Cursor, etc.)

```json
{
  "mcpServers": {
    "cdaweb": {
      "command": "xhelio-cdaweb-mcp"
    }
  }
}
```

Or run directly:

```bash
xhelio-cdaweb-mcp
python -m cdawebmcp
```

### Tools

| Tool | Description |
|------|-------------|
| `browse_missions()` | List all 54 CDAWeb missions with descriptions, dataset counts, and instruments |
| `load_mission(mission_id)` | Get the complete system prompt for a mission (role instructions + full dataset catalog) |
| `browse_parameters(dataset_id)` | Browse all variables in a dataset — name, type, units, description, plus validation status if available |
| `fetch_data(dataset_id, parameters, start, stop)` | Download CDF data, write to file, return metadata + per-column stats (min, max, mean, std, nan_ratio) |
| `manage_cache(action, ...)` | Cache management — status, clean, refresh metadata, refresh time ranges, rebuild catalog |

### Typical workflow

```
browse_missions  →  load_mission("ace")  →  browse_parameters("AC_H2_MFI")  →  fetch_data(...)
```

1. Discover available missions
2. Load a mission's full catalog and instructions
3. Inspect dataset parameters to choose what to fetch
4. Fetch data for a time range — returns file path + statistics

## Python Library

```python
from cdawebmcp.catalog import browse_missions
from cdawebmcp.prompts import build_mission_prompt
from cdawebmcp.metadata import browse_parameters
from cdawebmcp.fetch import fetch_data

# List all 54 missions
missions = browse_missions()

# Get mission-specific system prompt
prompt = build_mission_prompt("ace")

# Browse dataset parameters (instant — uses bundled metadata)
params = browse_parameters(dataset_id="AC_H2_MFI")

# Fetch data — returns DataFrames directly
result = fetch_data("AC_H2_MFI", ["Magnitude"], "2024-01-01", "2024-01-02")
mag = result["Magnitude"]
print(mag["data"])       # pandas DataFrame
print(mag["units"])      # "nT"
print(mag["stats"])      # per-column {min, max, mean, std, nan_ratio}
```

## Data validation

When `fetch_data` downloads CDF files, it automatically compares actual data variables against the bundled Master CDF metadata. Discrepancies are recorded in `~/.cdawebmcp/overrides/` and surfaced through `browse_parameters`:

- **Phantom parameters** — listed in metadata but absent from actual data files
- **Undocumented parameters** — present in data files but not in official metadata

This validation runs once per unique CDF source URL and builds an append-only archive with full provenance (source file, URL, timestamp).

## Bundled data

| Data | Count | Description |
|------|-------|-------------|
| Mission catalogs | 54 | Instruments, datasets, time coverage, PI info |
| Parameter metadata | 2541 | Variable names, types, units, fill values, sizes |
| Prompt templates | 2 | Generic role + CDAWeb-specific workflow instructions |

All bundled data ships with the package. No network access needed for browsing — only `fetch_data` requires a connection to CDAWeb.

## Catalog updates

Rebuild from CDAWeb REST API:

```bash
# Rebuild mission catalogs
python -m cdawebmcp.scripts.build_catalog
python -m cdawebmcp.scripts.build_catalog --mission psp
python -m cdawebmcp.scripts.build_catalog --discover

# Rebuild parameter metadata from Master CDFs
python -m cdawebmcp.scripts.build_metadata
python -m cdawebmcp.scripts.build_metadata --mission psp
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
