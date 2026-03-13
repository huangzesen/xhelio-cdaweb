# xhelio-cdaweb

NASA CDAWeb data access for heliophysics — browse observatories, inspect parameters, fetch CDF data.

Works as a standalone Python library or as an MCP server for any MCP-compatible LLM client (Claude Desktop, Cursor, custom agents).

## What's included

- **65 observatory catalogs** with 2900+ datasets — ACE, Parker Solar Probe, Solar Orbiter, Wind, MMS, THEMIS, GOES, Voyager, and more
- **2880 pre-built parameter metadata files** from Master CDF skeletons — `browse_parameters` works instantly, no network required
- **Automatic data validation** — fetched CDF files are compared against Master CDF metadata to detect phantom (documented but missing) and undocumented (present but undocumented) parameters
- **Structured system prompts** per observatory — give an LLM full context about available instruments, datasets, and time coverage

Observatory catalogs are built directly from the CDAWeb REST API observatory groups — no hand-curated mappings.

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

With custom cache directory:

```json
{
  "mcpServers": {
    "cdaweb": {
      "command": "xhelio-cdaweb-mcp",
      "args": ["--cache-dir", "/path/to/cache"]
    }
  }
}
```

Or run directly:

```bash
xhelio-cdaweb-mcp
xhelio-cdaweb-mcp --cache-dir /path/to/cache
python -m cdawebmcp
```

### Cache directory

All runtime data is stored under a single root directory. Defaults to `~/.cdawebmcp/`.

On first use, bundled data (observatory catalogs and parameter metadata) is copied into the cache directory. This ensures all reads and writes happen in one writable location, even for non-editable installs from PyPI.

Configure via `--cache-dir` (MCP server) or `cdawebmcp.configure()` (library):

```python
import cdawebmcp
cdawebmcp.configure(cache_dir="/path/to/cache")
```

```
~/.cdawebmcp/                  # or custom path via configure()
├── observatories/                  # Observatory catalog JSONs (bootstrapped from package)
├── metadata/                  # Parameter metadata JSONs (bootstrapped from package)
├── cdf_cache/                 # Downloaded CDF data files (permanent, reused across fetches)
│   └── ace/mfi/               #   organized by observatory/instrument path
│       └── ac_h2_mfi_2024.cdf
└── overrides/                 # Validation sync results (append-only)
    └── ace/
        └── AC_H2_MFI.json
```

- **`observatories/`** — Observatory catalog JSONs. Bootstrapped from bundled package data on first use.
- **`metadata/`** — Parameter metadata JSONs. Bootstrapped from bundled package data on first use. New metadata is fetched on demand from Master CDFs.
- **`cdf_cache/`** — Permanent cache of downloaded CDF files. Once a CDF file is downloaded, it is never re-downloaded. Use `manage_cache(action="clean", category="cdf_cache")` to free disk space.
- **`overrides/`** — Validation results from comparing fetched data against metadata. Append-only, one JSON per dataset.

### Tools

| Tool | Description |
|------|-------------|
| `browse_observatories()` | List all 65 CDAWeb observatories with descriptions, dataset counts, and instruments |
| `load_observatory(observatory_id)` | Get the complete system prompt for an observatory (role instructions + full dataset catalog) |
| `browse_parameters(dataset_id)` | Browse all variables in a dataset — name, type, units, description, plus validation status if available |
| `fetch_data(dataset_id, parameters, start, stop, output_dir)` | Download CDF data, write to file, return metadata + per-column stats (min, max, mean, std, nan_ratio) |
| `manage_cache(action, ...)` | Cache management — status, clean, refresh metadata, refresh time ranges, rebuild catalog |

### Typical workflow

```
browse_observatories  →  load_observatory("ace")  →  browse_parameters("AC_H2_MFI")  →  fetch_data(...)
```

1. Discover available observatories
2. Load an observatory's full catalog and instructions
3. Inspect dataset parameters to choose what to fetch
4. Fetch data for a time range — returns file path + statistics

## Python Library

```python
from cdawebmcp.catalog import browse_observatories
from cdawebmcp.prompts import build_observatory_prompt
from cdawebmcp.metadata import browse_parameters
from cdawebmcp.fetch import fetch_data

# List all 65 observatories
observatories = browse_observatories()

# Get observatory-specific system prompt
prompt = build_observatory_prompt("ace")

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
| Observatory catalogs | 65 | Instruments, datasets, time coverage, PI info |
| Parameter metadata | 2880 | Variable names, types, units, fill values, sizes |
| Prompt templates | 2 | Generic role + CDAWeb-specific workflow instructions |

All bundled data ships with the package and is copied to the cache directory on first use. No network access needed for browsing — only `fetch_data` requires a connection to CDAWeb.

## Catalog updates

Rebuild from CDAWeb REST API:

```bash
# Rebuild observatory catalogs (uses CDAWeb observatory groups API)
python -m cdawebmcp.scripts.build_catalog
python -m cdawebmcp.scripts.build_catalog --observatory ace
python -m cdawebmcp.scripts.build_catalog --list

# Rebuild parameter metadata from Master CDFs
python -m cdawebmcp.scripts.build_metadata
python -m cdawebmcp.scripts.build_metadata --observatory psp
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
