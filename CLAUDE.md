# CLAUDE.md — xhelio-cdaweb

## Project Overview

`xhelio-cdaweb` (PyPI name) / `cdawebmcp` (Python import) is a standalone package that provides NASA CDAWeb data access for heliophysics. Works as a Python library or an MCP server. Part of the xhelio ecosystem.

## Key Design Decisions

1. **Library-first, MCP optional.** Core library (`cdflib`, `pandas`, `requests`) has no MCP dependency. MCP server requires `pip install xhelio-cdaweb[mcp]`.
2. **`fetch_data` returns DataFrames directly** (library API). The MCP server wrapper writes to temp files and returns metadata + stats only.
3. **One MCP server serves all 54 CDAWeb missions.** `browse_missions` is the discovery entry point. `load_mission` returns a full system prompt.
4. **Mission catalog JSONs are bundled** in `src/cdawebmcp/data/missions/` (54 missions).

## Tech Stack

- Python 3.10+
- `mcp` (FastMCP) — MCP server SDK (optional)
- `cdflib` — CDF file reading
- `pandas` / `numpy` — DataFrame operations
- `requests` — HTTP client for CDAWeb API

## Commands

```bash
# Install library only
pip install -e .

# Install with MCP server
pip install -e ".[mcp]"

# Install with dev tools
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run the MCP server
xhelio-cdaweb-mcp
python -m cdawebmcp

# Build/rebuild mission catalog from CDAWeb API
python -m cdawebmcp.scripts.build_catalog
```

## Package Structure

```
src/cdawebmcp/
    __init__.py          # Package entry point
    __main__.py          # python -m cdawebmcp
    server.py            # MCP server (FastMCP) — 4 tools
    catalog.py           # Mission JSON loading + browse_missions
    prompts.py           # Prompt assembly for load_mission
    metadata.py          # Parameter metadata (Master CDF fetch + cache)
    fetch.py             # CDF download + file output + stats
    http.py              # HTTP client with retry logic
    data/
        missions/        # Bundled mission JSON files
        prompts/         # Prompt templates (generic_role.md, cdaweb_role.md)
    scripts/
        build_catalog.py # CDAWeb API → mission JSONs
```

## Reference: xhelio Source Files

These xhelio modules contain the code to extract from (DO NOT depend on xhelio — extract and adapt):

| xhelio file | Purpose | Maps to |
|---|---|---|
| `data_ops/fetch_cdf.py` | CDF download + DataFrame parsing | `fetch.py` |
| `data_ops/http_utils.py` | HTTP retry logic | `http.py` |
| `knowledge/metadata_client.py` + `knowledge/master_cdf.py` | Master CDF metadata | `metadata.py` |
| `knowledge/mission_prefixes.py` + `knowledge/cdaweb_metadata.py` | Mission prefix map, CDAWeb catalog | `scripts/build_catalog.py` |
| `knowledge/prompt_builder.py` | Envoy prompt assembly | `prompts.py` |
| `knowledge/prompts/envoy/generic_role.md` | Generic envoy role | `data/prompts/generic_role.md` |
| `knowledge/prompts/envoy_cdaweb/role.md` | CDAWeb-specific role | `data/prompts/cdaweb_role.md` |
| `scripts/generate_mission_data.py` | Catalog generation script | `scripts/build_catalog.py` |

The xhelio repo is at `../xhelio/` (master branch) if you need to read source files.
