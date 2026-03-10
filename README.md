# xhelio-cdaweb

NASA CDAWeb data access for heliophysics — browse missions, inspect parameters, fetch CDF data.

Works as a standalone Python library or as an MCP server for any MCP-compatible LLM client (Claude Desktop, Cursor, custom agents).

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
| `browse_missions()` | List all available CDAWeb missions with descriptions and dataset counts |
| `load_mission(mission_id)` | Get the complete system prompt for a mission (role instructions + dataset catalog) |
| `browse_parameters(dataset_id)` | Browse all variables in a dataset (name, type, units, description) |
| `fetch_data(dataset_id, parameters, start, stop)` | Download CDF data, write to file, return metadata + per-column stats |

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

# Browse dataset parameters
params = browse_parameters(dataset_id="AC_H2_MFI")

# Fetch data — returns DataFrames directly (no MCP needed)
result = fetch_data("AC_H2_MFI", ["Magnitude"], "2024-01-01", "2024-01-02")
mag = result["Magnitude"]
print(mag["data"])       # pandas DataFrame
print(mag["units"])      # "nT"
print(mag["stats"])      # per-column {min, max, mean, std, nan_ratio}
```

## Catalog Updates

54 mission catalog JSONs are bundled. Rebuild from CDAWeb REST API:

```bash
python -m cdawebmcp.scripts.build_catalog
python -m cdawebmcp.scripts.build_catalog --mission psp
python -m cdawebmcp.scripts.build_catalog --discover
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
