# cdawebmcp

MCP server for NASA CDAWeb — browse missions, inspect parameters, fetch heliophysics data.

Any MCP-compatible LLM client (Claude Desktop, Cursor, custom agents) can use this server to discover missions, load mission-specific system prompts, browse dataset parameters, and fetch CDF data from NASA's Coordinated Data Analysis Web archive.

## Installation

```bash
pip install cdawebmcp
```

## MCP Server Configuration

### stdio transport (Claude Desktop, Cursor, etc.)

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

## Tools

### `browse_missions()`

List all available CDAWeb missions with descriptions, dataset counts, and instrument names. Call this first to discover what's available.

### `load_mission(mission_id)`

Load the complete system prompt for a mission. Returns role instructions, CDAWeb workflow, and the full dataset catalog as markdown. Any LLM consuming this becomes a specialist for that mission.

### `browse_parameters(dataset_id)`

Browse all parameters (variables) for a CDAWeb dataset. Returns name, type, units, description, size, and fill value. Use this to discover what variables a dataset contains before fetching.

### `fetch_data(dataset_id, parameters, start, stop)`

Fetch timeseries data from CDAWeb. Downloads CDF files, extracts parameters, writes data to a file on disk, and returns rich metadata including per-column statistics (min, max, mean, std, nan_ratio). Data is NOT returned inline — read the file at the returned path.

## Python Library Usage

```python
from cdawebmcp.catalog import browse_missions
from cdawebmcp.prompts import build_mission_prompt
from cdawebmcp.metadata import browse_parameters
from cdawebmcp.fetch import fetch_data

# List missions
missions = browse_missions()

# Get mission-specific system prompt
prompt = build_mission_prompt("ace")

# Browse dataset parameters
params = browse_parameters(dataset_id="AC_H2_MFI")

# Fetch data — returns DataFrames directly
result = fetch_data("AC_H2_MFI", ["Magnitude"], "2024-01-01", "2024-01-02")
mag = result["Magnitude"]
print(mag["data"])       # pandas DataFrame
print(mag["units"])      # "nT"
print(mag["stats"])      # per-column {min, max, mean, std, nan_ratio}
```

## Catalog Updates

Mission catalog JSONs are bundled with the package. To rebuild from the CDAWeb REST API:

```bash
python -m cdawebmcp.scripts.build_catalog
python -m cdawebmcp.scripts.build_catalog --mission psp  # single mission
python -m cdawebmcp.scripts.build_catalog --discover      # show unmatched datasets
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

MIT
