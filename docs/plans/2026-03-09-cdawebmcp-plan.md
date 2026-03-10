# cdawebmcp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `cdawebmcp`, a standalone Python package that exposes NASA CDAWeb as an MCP server with 4 tools: `browse_missions`, `load_mission`, `browse_parameters`, `fetch_data`.

**Architecture:** FastMCP server with bundled mission catalog JSONs, on-demand parameter metadata from Master CDFs (cached locally), and CDF data fetching via CDAWeb REST API. `fetch_data` writes data to a temp file and returns metadata + file path (not data inline) — follows the same pattern as `heliospice`'s ephemeris handler. One MCP server serves all ~40+ CDAWeb missions; `browse_missions` is the discovery entry point for standalone consumers.

**Tech Stack:** Python 3.10+, `mcp` (FastMCP), `cdflib`, `pandas`, `numpy`, `requests`

**Design doc:** `docs/plans/2026-03-09-cdawebmcp-design.md`

---

## Task 1: Repository scaffold and package structure

**Files:**
- Create: `cdawebmcp/pyproject.toml`
- Create: `cdawebmcp/README.md`
- Create: `cdawebmcp/src/cdawebmcp/__init__.py`
- Create: `cdawebmcp/src/cdawebmcp/__main__.py`
- Create: `cdawebmcp/src/cdawebmcp/py.typed`

**Step 1: Create the repo directory**

Create `cdawebmcp/` as a sibling to the xhelio repo (at `~/Documents/GitHub/cdawebmcp/`). Initialize git.

```bash
mkdir -p ~/Documents/GitHub/cdawebmcp
cd ~/Documents/GitHub/cdawebmcp
git init
```

**Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cdawebmcp"
version = "0.1.0"
description = "MCP server for NASA CDAWeb — browse missions, inspect parameters, fetch data"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [
    { name = "Zesen Huang" },
]
keywords = ["mcp", "cdaweb", "nasa", "heliophysics", "space-weather"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "Topic :: Scientific/Engineering :: Astronomy",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
]
dependencies = [
    "mcp>=1.0",
    "cdflib>=1.0",
    "pandas>=2.0",
    "numpy>=1.24",
    "requests>=2.28",
]

[project.scripts]
cdawebmcp = "cdawebmcp:main"

[tool.hatch.build.targets.wheel]
packages = ["src/cdawebmcp"]
```

**Step 3: Create package __init__.py**

```python
"""cdawebmcp — MCP server for NASA CDAWeb data access."""

__version__ = "0.1.0"


def main():
    """Entry point for the cdawebmcp CLI."""
    from cdawebmcp.server import serve
    serve()
```

**Step 4: Create __main__.py**

```python
"""Allow running as `python -m cdawebmcp`."""
from cdawebmcp import main

main()
```

**Step 5: Create py.typed marker**

Empty file at `src/cdawebmcp/py.typed`.

**Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold cdawebmcp package"
```

---

## Task 2: HTTP utilities

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/http.py`
- Create: `cdawebmcp/tests/test_http.py`

**Step 1: Write the test**

```python
"""Tests for HTTP retry logic."""
import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

from cdawebmcp.http import request_with_retry


def test_request_success():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        resp = request_with_retry("https://example.com")
        assert resp.status_code == 200
        mock_get.assert_called_once()


def test_request_retry_on_timeout():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_get.side_effect = [Timeout(), Timeout(), MagicMock(status_code=200)]
        mock_get.return_value = MagicMock(status_code=200)
        # Reset side_effect after setup
        mock_resp = MagicMock(status_code=200)
        mock_get.side_effect = [Timeout(), Timeout(), mock_resp]
        resp = request_with_retry("https://example.com", retries=3, backoff=0)
        assert resp.status_code == 200
        assert mock_get.call_count == 3


def test_request_raises_after_retries():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_get.side_effect = Timeout()
        with pytest.raises(Timeout):
            request_with_retry("https://example.com", retries=2, backoff=0)
        assert mock_get.call_count == 2
```

**Step 2: Run test to verify it fails**

```bash
cd ~/Documents/GitHub/cdawebmcp
pip install -e ".[dev]" 2>/dev/null || pip install -e .
python -m pytest tests/test_http.py -v
```

Expected: FAIL (module not found)

**Step 3: Write implementation**

Extract from xhelio's `data_ops/http_utils.py`, removing event bus dependency:

```python
"""HTTP utilities — request helpers with retry logic."""

import logging
import time as _time

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1  # seconds (doubles each retry)


def request_with_retry(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    **kwargs,
) -> requests.Response:
    """GET request with retry on timeout/connection errors.

    Args:
        url: URL to fetch.
        timeout: Per-request timeout in seconds.
        retries: Max number of attempts.
        backoff: Initial backoff in seconds (doubles each retry).
        **kwargs: Passed to requests.get().

    Returns:
        Response object.

    Raises:
        Last exception if all retries fail.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                wait = backoff * (2 ** (attempt - 1))
                logger.debug("Retry %d/%d for %s (wait %.1fs): %s",
                             attempt, retries, url, wait, e)
                _time.sleep(wait)
    raise last_exc
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_http.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/http.py tests/test_http.py
git commit -m "feat: add HTTP request utility with retry logic"
```

---

## Task 3: Mission catalog module

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/catalog.py`
- Create: `cdawebmcp/tests/test_catalog.py`
- Create: `cdawebmcp/src/cdawebmcp/data/missions/` (directory)

This module loads mission JSON files bundled in the package and provides `browse_missions()` and `load_mission()` data.

**Step 1: Write the test**

```python
"""Tests for mission catalog loading."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.catalog import (
    get_missions_dir,
    load_mission_json,
    browse_missions,
    mission_to_markdown,
)


@pytest.fixture
def sample_mission(tmp_path):
    """Create a minimal mission JSON for testing."""
    mission = {
        "id": "ACE",
        "name": "ACE",
        "profile": {
            "description": "ACE spacecraft data from CDAWeb.",
            "coordinate_systems": ["GSE", "GSM"],
            "typical_cadence": "16s",
            "data_caveats": [],
        },
        "instruments": {
            "mag": {
                "name": "Magnetic Fields",
                "keywords": ["magnetic", "field"],
                "datasets": {
                    "AC_H2_MFI": {
                        "description": "ACE MFI 16-Second Level 2 Data",
                        "start_date": "1998-01-01",
                        "stop_date": "2026-01-01",
                        "pi_name": "N. Ness",
                    }
                },
            }
        },
    }
    mission_file = tmp_path / "ace.json"
    mission_file.write_text(json.dumps(mission))
    return tmp_path, mission


def test_load_mission_json(sample_mission):
    missions_dir, expected = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        result = load_mission_json("ace")
    assert result["id"] == "ACE"
    assert "mag" in result["instruments"]


def test_browse_missions(sample_mission):
    missions_dir, _ = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        result = browse_missions()
    assert len(result) == 1
    assert result[0]["id"] == "ACE"
    assert result[0]["description"] == "ACE spacecraft data from CDAWeb."
    assert result[0]["dataset_count"] == 1


def test_mission_to_markdown(sample_mission):
    missions_dir, _ = sample_mission
    with patch("cdawebmcp.catalog.get_missions_dir", return_value=missions_dir):
        mission = load_mission_json("ace")
    md = mission_to_markdown(mission)
    assert "## Dataset Catalog" in md
    assert "AC_H2_MFI" in md
    assert "N. Ness" in md
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_catalog.py -v
```

**Step 3: Write implementation**

```python
"""Mission catalog — load bundled mission JSONs and generate summaries."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Package data directory
_PACKAGE_DATA = Path(__file__).parent / "data"


def get_missions_dir() -> Path:
    """Return the path to the bundled missions directory."""
    return _PACKAGE_DATA / "missions"


def load_mission_json(mission_stem: str) -> dict:
    """Load a mission JSON file by stem name (e.g., 'ace', 'psp').

    Args:
        mission_stem: Lowercase mission identifier.

    Returns:
        Parsed mission dict.

    Raises:
        FileNotFoundError: If no JSON file exists for this mission.
    """
    filepath = get_missions_dir() / f"{mission_stem}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Mission file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def browse_missions() -> list[dict]:
    """List all available missions with summaries.

    Returns:
        List of dicts with: id, name, description, dataset_count, instruments.
    """
    missions_dir = get_missions_dir()
    if not missions_dir.exists():
        return []

    results = []
    for filepath in sorted(missions_dir.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mission = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)
            continue

        # Count datasets across all instruments
        dataset_count = sum(
            len(inst.get("datasets", {}))
            for inst in mission.get("instruments", {}).values()
        )

        profile = mission.get("profile", {})
        results.append({
            "id": mission.get("id", filepath.stem.upper()),
            "name": mission.get("name", filepath.stem),
            "description": profile.get("description", ""),
            "dataset_count": dataset_count,
            "instruments": list(mission.get("instruments", {}).keys()),
        })

    return results


def mission_to_markdown(mission: dict) -> str:
    """Convert a mission JSON dict to a readable markdown dataset catalog.

    Args:
        mission: Full mission dict from load_mission_json().

    Returns:
        Markdown string with dataset catalog.
    """
    lines = ["## Dataset Catalog", ""]
    for inst_name, inst_data in sorted(mission.get("instruments", {}).items()):
        lines.append(f"### {inst_name}")
        if inst_data.get("keywords"):
            lines.append(f"Keywords: {', '.join(inst_data['keywords'])}")
        lines.append("")
        for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
            desc = ds_info.get("description", "")
            start = ds_info.get("start_date", "?")
            stop = ds_info.get("stop_date", "?")
            lines.append(f"- **{ds_id}**: {desc}")
            lines.append(f"  Coverage: {start} to {stop}")
            if ds_info.get("pi_name"):
                lines.append(f"  PI: {ds_info['pi_name']}")
            if ds_info.get("doi"):
                lines.append(f"  DOI: {ds_info['doi']}")
        lines.append("")
    return "\n".join(lines)


def get_mission_stem_from_dataset(dataset_id: str) -> str | None:
    """Find which mission a dataset belongs to by scanning all mission JSONs.

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').

    Returns:
        Mission stem (e.g., 'ace') or None.
    """
    missions_dir = get_missions_dir()
    if not missions_dir.exists():
        return None

    for filepath in missions_dir.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mission = json.load(f)
            for inst in mission.get("instruments", {}).values():
                if dataset_id in inst.get("datasets", {}):
                    return filepath.stem
        except (json.JSONDecodeError, OSError):
            continue
    return None
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_catalog.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/catalog.py tests/test_catalog.py
git commit -m "feat: add mission catalog module with browse and markdown rendering"
```

---

## Task 4: Prompt assembly module

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/prompts.py`
- Create: `cdawebmcp/src/cdawebmcp/data/prompts/generic_role.md`
- Create: `cdawebmcp/src/cdawebmcp/data/prompts/cdaweb_role.md`
- Create: `cdawebmcp/tests/test_prompts.py`

The prompts are adapted from xhelio's envoy prompts — xhelio-specific references (orchestrator, sub-agents, events tool) are removed. The prompt teaches any LLM how to use `browse_parameters` and `fetch_data` effectively.

**Step 1: Create prompt templates**

`data/prompts/generic_role.md`:
```markdown
You are a CDAWeb data specialist — an expert in NASA's Coordinated Data Analysis Web archive.

## Your Role

- You know your mission's instruments, datasets, and data access methods.
- Your dataset catalog is embedded below — use it to identify the right datasets for user requests.
- Use `browse_parameters` to inspect dataset variables before fetching.
- Use `fetch_data` to download data.
```

`data/prompts/cdaweb_role.md`:
```markdown
## CDAWeb Data Access

You access data from NASA's Coordinated Data Analysis Web (CDAWeb) archive.

- Dataset IDs follow CDAWeb naming: `{MISSION}_{INSTRUMENT}_{LEVEL}_{TYPE}` (e.g., `PSP_FLD_L2_MAG_RTN_1MIN`).
- Parameter names come from CDF variable names — use `browse_parameters` to discover them.
- CDAWeb data is typically in standard coordinate systems (GSE, GSM, RTN, etc.).

## Dataset Discovery

Your context contains the complete dataset catalog for this mission — every instrument,
dataset ID, description, and time coverage. Use this to identify the right dataset for the
user's request. Then call `browse_parameters(dataset_id)` to see available variables before
fetching.

## Dataset Selection Workflow

1. **Pick a dataset** from the Dataset Catalog. Match on description,
   instrument keywords, and time coverage.
2. **Browse parameters**: Call `browse_parameters(dataset_id)` to see all
   available variables. Select the best parameters based on name, units, and description.
3. **Fetch data**: Call `fetch_data` for each relevant parameter.
4. **If a parameter returns all-NaN**: Skip it and try the next candidate dataset.

## Data Availability Validation

Check each candidate dataset's `Coverage` against the requested time range BEFORE fetching.
If ≥90% of the requested time range falls outside all candidate datasets' coverage, do NOT
attempt to fetch — inform the user.
```

**Step 2: Write the test**

```python
"""Tests for prompt assembly."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cdawebmcp.prompts import build_mission_prompt


@pytest.fixture
def mock_catalog(tmp_path):
    """Set up mock mission data and prompts."""
    # Mission JSON
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()
    mission = {
        "id": "ACE",
        "name": "ACE",
        "profile": {"description": "ACE data from CDAWeb."},
        "instruments": {
            "mag": {
                "name": "Magnetic Fields",
                "keywords": ["magnetic"],
                "datasets": {
                    "AC_H2_MFI": {
                        "description": "MFI 16-sec data",
                        "start_date": "1998-01-01",
                        "stop_date": "2026-01-01",
                    }
                },
            }
        },
    }
    (missions_dir / "ace.json").write_text(json.dumps(mission))

    # Prompt templates
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "generic_role.md").write_text("You are a CDAWeb specialist.")
    (prompts_dir / "cdaweb_role.md").write_text("## CDAWeb Access\nUse browse_parameters.")

    return tmp_path


def test_build_mission_prompt(mock_catalog):
    with patch("cdawebmcp.prompts._PACKAGE_DATA", mock_catalog):
        prompt = build_mission_prompt("ace")
    assert "CDAWeb specialist" in prompt
    assert "CDAWeb Access" in prompt
    assert "AC_H2_MFI" in prompt
    assert "Dataset Catalog" in prompt


def test_build_mission_prompt_not_found(mock_catalog):
    with patch("cdawebmcp.prompts._PACKAGE_DATA", mock_catalog):
        with pytest.raises(FileNotFoundError):
            build_mission_prompt("nonexistent")
```

**Step 3: Write implementation**

```python
"""Prompt assembly — builds mission-specific system prompts."""

from pathlib import Path

from cdawebmcp.catalog import load_mission_json, mission_to_markdown

_PACKAGE_DATA = Path(__file__).parent / "data"


def _load_prompt_template(filename: str) -> str:
    """Load a prompt template from the package data directory."""
    filepath = _PACKAGE_DATA / "prompts" / filename
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8").strip()


def build_mission_prompt(mission_stem: str) -> str:
    """Build the complete system prompt for a mission.

    Assembles three layers:
    1. Generic role instructions
    2. CDAWeb-specific workflow instructions
    3. Mission profile + full dataset catalog as markdown

    Args:
        mission_stem: Lowercase mission identifier (e.g., 'ace', 'psp').

    Returns:
        Complete system prompt string.

    Raises:
        FileNotFoundError: If no mission JSON exists.
    """
    # Layer 1: Generic role
    generic_role = _load_prompt_template("generic_role.md")

    # Layer 2: CDAWeb-specific
    cdaweb_role = _load_prompt_template("cdaweb_role.md")

    # Layer 3: Mission data
    mission = load_mission_json(mission_stem)
    profile = mission.get("profile", {})

    # Mission overview
    overview_lines = []
    name = mission.get("name", mission_stem.upper())
    overview_lines.append(f"## Mission: {name}")
    if profile.get("description"):
        overview_lines.append(profile["description"])
    coords = profile.get("coordinate_systems", [])
    if coords:
        overview_lines.append(f"- Coordinate system(s): {', '.join(coords)}")
    cadence = profile.get("typical_cadence")
    if cadence:
        overview_lines.append(f"- Typical cadence: {cadence}")
    if profile.get("data_caveats"):
        overview_lines.append("- Data caveats: " + "; ".join(profile["data_caveats"]))
    overview_lines.append("")
    mission_overview = "\n".join(overview_lines)

    # Dataset catalog
    dataset_catalog = mission_to_markdown(mission)

    # Assemble
    parts = [p for p in [generic_role, cdaweb_role, mission_overview, dataset_catalog] if p]
    return "\n\n".join(parts)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_prompts.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/prompts.py src/cdawebmcp/data/prompts/ tests/test_prompts.py
git commit -m "feat: add prompt assembly for load_mission"
```

---

## Task 5: Parameter metadata module (Master CDF)

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/metadata.py`
- Create: `cdawebmcp/tests/test_metadata.py`

Extracted from xhelio's `knowledge/master_cdf.py`, removing event bus dependency.

**Step 1: Write the test**

```python
"""Tests for parameter metadata resolution."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cdawebmcp.metadata import (
    get_cache_dir,
    browse_parameters,
)


def test_browse_parameters_from_cache(tmp_path):
    """Test loading parameters from local metadata cache."""
    cache_dir = tmp_path / "metadata"
    cache_dir.mkdir()

    metadata = {
        "parameters": [
            {"name": "Time", "type": "isotime", "units": "UTC"},
            {"name": "BGSEc", "type": "double", "units": "nT",
             "description": "Magnetic field GSE", "size": [3]},
            {"name": "Magnitude", "type": "double", "units": "nT",
             "description": "Field magnitude"},
        ],
        "startDate": "1998-01-01",
        "stopDate": "2026-01-01",
    }
    (cache_dir / "AC_H2_MFI.json").write_text(json.dumps(metadata))

    with patch("cdawebmcp.metadata.get_cache_dir", return_value=cache_dir):
        result = browse_parameters("AC_H2_MFI")

    assert result["status"] == "success"
    assert result["dataset_id"] == "AC_H2_MFI"
    # Time parameter should be filtered out
    param_names = [p["name"] for p in result["parameters"]]
    assert "Time" not in param_names
    assert "BGSEc" in param_names
    assert "Magnitude" in param_names


def test_browse_parameters_missing_dataset(tmp_path):
    """Test that missing datasets trigger Master CDF download."""
    cache_dir = tmp_path / "metadata"
    cache_dir.mkdir()

    with patch("cdawebmcp.metadata.get_cache_dir", return_value=cache_dir):
        with patch("cdawebmcp.metadata._fetch_from_master_cdf") as mock_fetch:
            mock_fetch.return_value = {
                "parameters": [
                    {"name": "Magnitude", "type": "double", "units": "nT"},
                ],
                "startDate": "",
                "stopDate": "",
            }
            result = browse_parameters("FAKE_DATASET")

    assert result["status"] == "success"
    mock_fetch.assert_called_once()
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_metadata.py -v
```

**Step 3: Write implementation**

```python
"""Parameter metadata — browse dataset variables via local cache or Master CDFs."""

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".cdawebmcp" / "metadata"

MASTER_CDF_BASE = "https://cdaweb.gsfc.nasa.gov/pub/software/cdawlib/0MASTERS"

# CDF type string -> parameter type mapping
_CDF_TYPE_MAP = {
    "CDF_REAL4": "double", "CDF_REAL8": "double",
    "CDF_DOUBLE": "double", "CDF_FLOAT": "double",
    "CDF_INT1": "integer", "CDF_INT2": "integer",
    "CDF_INT4": "integer", "CDF_INT8": "integer",
    "CDF_UINT1": "integer", "CDF_UINT2": "integer",
    "CDF_UINT4": "integer", "CDF_BYTE": "integer",
}

_SKIP_TYPES = {
    "CDF_EPOCH", "CDF_EPOCH16", "CDF_TIME_TT2000",
    "CDF_CHAR", "CDF_UCHAR",
}


def get_cache_dir() -> Path:
    """Return the metadata cache directory. Configurable via env var."""
    import os
    custom = os.environ.get("CDAWEBMCP_CACHE_DIR")
    if custom:
        return Path(custom) / "metadata"
    return _DEFAULT_CACHE_DIR


def browse_parameters(
    dataset_id: str | None = None,
    dataset_ids: list[str] | None = None,
) -> dict:
    """Browse parameters for one or more datasets.

    Resolution chain:
    1. Local metadata cache (~/.cdawebmcp/metadata/{dataset_id}.json)
    2. Master CDF download from CDAWeb (fallback, then cached)

    Args:
        dataset_id: Single dataset ID.
        dataset_ids: Multiple dataset IDs for batch lookup.

    Returns:
        Dict with status and parameter metadata.
    """
    ids: list[str] = []
    if dataset_ids:
        ids = dataset_ids
    elif dataset_id:
        ids = [dataset_id]

    if not ids:
        return {"status": "error", "message": "Missing required parameter: dataset_id or dataset_ids"}

    results: dict[str, dict] = {}
    for ds_id in ids:
        try:
            info = _resolve_metadata(ds_id)
            params = [p for p in info.get("parameters", [])
                      if p.get("name", "").lower() != "time"]
            entry: dict = {"parameters": params}
            start = info.get("startDate", "")
            stop = info.get("stopDate", "")
            if start or stop:
                entry["time_range"] = {"start": start, "stop": stop}
        except Exception as e:
            logger.warning("Could not load parameters for %s: %s", ds_id, e)
            entry = {"parameters": [], "error": str(e)}
        results[ds_id] = entry

    # Flatten for single-dataset calls
    if len(results) == 1:
        ds_id, entry = next(iter(results.items()))
        return {"status": "success", "dataset_id": ds_id, **entry}

    return {"status": "success", "datasets": results}


def _resolve_metadata(dataset_id: str) -> dict:
    """Resolve parameter metadata: local cache first, then Master CDF.

    Side effect: caches the result locally after Master CDF download.
    """
    cache_dir = get_cache_dir()
    cache_file = cache_dir / f"{dataset_id}.json"

    # Try local cache
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: Master CDF
    info = _fetch_from_master_cdf(dataset_id)
    if info is None:
        raise RuntimeError(f"Could not fetch metadata for {dataset_id}")

    # Cache the result
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    return info


def _fetch_from_master_cdf(dataset_id: str) -> dict | None:
    """Download a Master CDF skeleton and extract parameter metadata."""
    try:
        import cdflib
    except ImportError:
        raise RuntimeError("cdflib is required for Master CDF reading")

    from cdawebmcp.http import request_with_retry

    url = f"{MASTER_CDF_BASE}/{dataset_id.lower()}_00000000_v01.cdf"
    logger.info("Downloading Master CDF: %s", url)

    try:
        resp = request_with_retry(url)
    except Exception as e:
        logger.warning("Master CDF download failed for %s: %s", dataset_id, e)
        return None

    # Write to temp file for cdflib
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".cdf", delete=False) as tmp:
        tmp.write(resp.content)
        tmp_path = Path(tmp.name)

    try:
        return _extract_metadata(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _extract_metadata(cdf_path: Path) -> dict:
    """Extract parameter metadata from a Master CDF file."""
    import cdflib

    cdf = cdflib.CDF(str(cdf_path))
    cdf_info = cdf.cdf_info()

    parameters = [
        {"name": "Time", "type": "isotime", "units": "UTC", "fill": None}
    ]

    all_vars = list(cdf_info.zVariables) + list(cdf_info.rVariables)

    for var_name in all_vars:
        try:
            var_inq = cdf.varinq(var_name)
        except Exception:
            continue

        dtype_desc = var_inq.Data_Type_Description
        if dtype_desc in _SKIP_TYPES:
            continue

        param_type = _CDF_TYPE_MAP.get(dtype_desc)
        if param_type is None:
            continue

        # Check VAR_TYPE
        try:
            attrs = cdf.varattsget(var_name)
            var_type = attrs.get("VAR_TYPE", "")
            if isinstance(var_type, np.ndarray):
                var_type = str(var_type)
            if var_type and var_type.lower() not in ("data", "ignore_data"):
                continue
        except Exception:
            pass

        try:
            attrs = cdf.varattsget(var_name)
        except Exception:
            attrs = {}

        description = _get_str_attr(attrs, "CATDESC") or _get_str_attr(attrs, "FIELDNAM") or ""
        units = _get_str_attr(attrs, "UNITS") or ""

        fill = None
        raw_fill = attrs.get("FILLVAL", None)
        if raw_fill is not None:
            try:
                fill = str(float(raw_fill))
            except (ValueError, TypeError):
                pass

        dim_sizes = var_inq.Dim_Sizes
        if isinstance(dim_sizes, (list, np.ndarray)) and len(dim_sizes) > 0:
            size = [int(d) for d in dim_sizes]
            while len(size) > 1 and size[0] == 1:
                size = size[1:]
        else:
            size = [1]

        param = {
            "name": var_name,
            "type": param_type,
            "units": units,
            "description": description,
            "fill": fill,
        }
        if size != [1]:
            param["size"] = size

        parameters.append(param)

    return {"parameters": parameters, "startDate": "", "stopDate": ""}


def _get_str_attr(attrs: dict, key: str) -> str:
    """Extract a string attribute from CDF variable attributes."""
    val = attrs.get(key, "")
    if val is None:
        return ""
    if isinstance(val, np.ndarray):
        val = str(val.flat[0]) if val.size > 0 else ""
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="replace")
    if isinstance(val, (int, float)):
        return str(val)
    return str(val).strip() if val else ""
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_metadata.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/metadata.py tests/test_metadata.py
git commit -m "feat: add parameter metadata module with Master CDF fallback"
```

---

## Task 6: Data fetching module

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/fetch.py`
- Create: `cdawebmcp/tests/test_fetch.py`

Extracted from xhelio's `data_ops/fetch_cdf.py`, adapted to write data to a temp file and return metadata (not data inline). This follows the same pattern as `heliospice`'s `get_ephemeris` handler.

**Step 1: Write the test**

```python
"""Tests for CDF data fetching — unit tests with mocked network."""
import json
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from pathlib import Path

from cdawebmcp.fetch import write_dataframe_csv, write_dataframe_json


def test_write_dataframe_csv(tmp_path):
    """Test DataFrame → CSV file output."""
    times = pd.date_range("2024-01-01", periods=5, freq="h")
    df = pd.DataFrame({1: np.arange(5.0), 2: np.arange(5.0, 10.0)}, index=times)
    df.index.name = "time"

    out_path = write_dataframe_csv(df, tmp_path, "test_param")
    assert out_path.exists()
    assert out_path.suffix == ".csv"
    content = out_path.read_text()
    assert "time" in content
    assert "0.0" in content


def test_write_dataframe_json(tmp_path):
    """Test DataFrame → JSON file output."""
    times = pd.date_range("2024-01-01", periods=5, freq="h")
    df = pd.DataFrame({1: np.arange(5.0)}, index=times)
    df.index.name = "time"

    out_path = write_dataframe_json(df, tmp_path, "test_param")
    assert out_path.exists()
    assert out_path.suffix == ".json"
    data = json.loads(out_path.read_text())
    assert "time" in data
    assert len(data["time"]) == 5


def test_fetch_data_returns_metadata_not_data(tmp_path):
    """Test that fetch_data returns metadata + file_path, not data."""
    # This test would need mocked network calls — structure it to verify
    # the return shape has file_path and no inline data.
    pass  # Detailed in integration smoke test (Task 10)
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_fetch.py -v
```

**Step 3: Write implementation**

This is the largest module. Extract core logic from `data_ops/fetch_cdf.py`:

```python
"""CDF data fetching — download from CDAWeb and return DataFrames.

Library API: fetch_data() returns DataFrames + stats directly.
MCP server wrapper (server.py) handles file-writing and metadata-only responses.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CDAWEB_REST_BASE = "https://cdaweb.gsfc.nasa.gov/WS/cdasr/1/dataviews/sp_phys"

_WARN_THRESHOLD_BYTES = 500 * 1024 * 1024   # 500 MB
_BLOCK_THRESHOLD_BYTES = 1024 * 1024 * 1024  # 1 GB

_EPOCH_TYPES = {"CDF_EPOCH", "CDF_EPOCH16", "CDF_TIME_TT2000"}
_SKIP_TYPES = _EPOCH_TYPES | {"CDF_CHAR", "CDF_UCHAR"}


def get_cache_dir() -> Path:
    """Return the CDF file cache directory."""
    import os
    custom = os.environ.get("CDAWEBMCP_CACHE_DIR")
    if custom:
        return Path(custom) / "cdf_cache"
    return Path.home() / ".cdawebmcp" / "cdf_cache"


def fetch_data(
    dataset_id: str,
    parameters: list[str],
    start: str,
    stop: str,
    force: bool = False,
) -> dict:
    """Fetch CDAWeb timeseries data and return DataFrames with stats.

    This is the library API — returns DataFrames directly. The MCP server
    wrapper in server.py handles file-writing and metadata-only responses.

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').
        parameters: List of parameter names to fetch.
        start: Start time in ISO 8601 format.
        stop: End time in ISO 8601 format.
        force: Override the 1 GB download safety limit.

    Returns:
        Dict keyed by parameter_id. Each value has:
        - data: pandas DataFrame with DatetimeIndex
        - units: str
        - description: str
        - stats: dict of per-column {min, max, mean, std, nan_ratio}
        On error, the value has just {"error": str}.
    """
    from cdawebmcp.metadata import _resolve_metadata

    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Resolve metadata for units/descriptions
    try:
        info = _resolve_metadata(dataset_id)
    except Exception:
        info = {"parameters": []}

    results = {}
    for param_id in parameters:
        try:
            result = _fetch_single_parameter(
                dataset_id, param_id, start, stop, info, cache_dir, force
            )
            df = result["data"]

            # Compute per-column statistics
            stats = {}
            for col in df.columns:
                series = df[col]
                nan_count = int(series.isna().sum())
                total = len(series)
                stats[str(col)] = {
                    "min": round(float(series.min()), 4) if not series.isna().all() else None,
                    "max": round(float(series.max()), 4) if not series.isna().all() else None,
                    "mean": round(float(series.mean()), 4) if not series.isna().all() else None,
                    "std": round(float(series.std()), 4) if not series.isna().all() else None,
                    "nan_ratio": round(nan_count / total, 4) if total > 0 else 0.0,
                }

            results[param_id] = {
                "data": df,
                "units": result["units"],
                "description": result["description"],
                "stats": stats,
            }
        except Exception as e:
            results[param_id] = {"error": str(e)}

    return results


def _fetch_single_parameter(
    dataset_id: str,
    parameter_id: str,
    time_min: str,
    time_max: str,
    info: dict,
    cache_dir: Path,
    force: bool,
) -> dict:
    """Fetch a single parameter from CDAWeb CDF files.

    Returns dict with keys: data (DataFrame), units, description, fill_value.
    """
    import cdflib

    # Look up parameter metadata
    units = ""
    description = ""
    fill_value = None
    cdf_native = False
    try:
        param_meta = _find_parameter_meta(info, parameter_id)
        units = param_meta.get("units", "")
        description = param_meta.get("description", "")
        fill_value = param_meta.get("fill", None)
    except ValueError:
        cdf_native = True

    # Get CDF file list
    from cdawebmcp.http import request_with_retry
    file_list = _get_cdf_file_list(dataset_id, time_min, time_max)
    logger.info("Found %d CDF files for %s (%s to %s)",
                len(file_list), dataset_id, time_min, time_max)

    # Download and read each file
    frames = []
    validmin = None
    validmax = None

    max_workers = min(len(file_list), 6)
    if len(file_list) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_download_and_read, fi["url"], parameter_id, cache_dir): idx
                for idx, fi in enumerate(file_list)
            }
            results_by_idx = {}
            for future in as_completed(futures):
                idx = futures[future]
                results_by_idx[idx] = future.result()
    else:
        results_by_idx = {}
        for idx, fi in enumerate(file_list):
            results_by_idx[idx] = _download_and_read(fi["url"], parameter_id, cache_dir)

    for idx in range(len(file_list)):
        local_path, data = results_by_idx[idx]
        if not frames:
            try:
                cdf = cdflib.CDF(str(local_path))
                attrs = cdf.varattsget(parameter_id)
                if cdf_native:
                    units = attrs.get("UNITS", "") or ""
                    if isinstance(units, np.ndarray):
                        units = str(units)
                    description = (attrs.get("CATDESC", "")
                                   or attrs.get("FIELDNAM", "") or "")
                    if isinstance(description, np.ndarray):
                        description = str(description)
                fv = attrs.get("FILLVAL", None)
                if fv is not None:
                    try:
                        fill_value = float(fv)
                    except (ValueError, TypeError):
                        pass
                vmin = attrs.get("VALIDMIN", None)
                vmax = attrs.get("VALIDMAX", None)
                if vmin is not None:
                    try:
                        validmin = float(vmin)
                    except (ValueError, TypeError):
                        pass
                if vmax is not None:
                    try:
                        validmax = float(vmax)
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass
        frames.append(data)

    if not frames:
        raise ValueError(f"No data for {dataset_id}/{parameter_id} in {time_min} to {time_max}")

    # Concatenate and clean
    df = pd.concat(frames)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="first")]

    t_start = _strip_utc_suffix(time_min)
    t_stop = _strip_utc_suffix(time_max)
    df = df.loc[t_start:t_stop]

    if len(df) == 0:
        raise ValueError(f"No data rows in range {time_min} to {time_max}")

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    if fill_value is not None:
        try:
            fill_f = float(fill_value)
            for col in df.columns:
                mask = np.isclose(df[col].values, fill_f, rtol=1e-6, equal_nan=False)
                df.loc[mask, col] = np.nan
        except (ValueError, TypeError):
            pass

    if validmin is not None or validmax is not None:
        for col in df.columns:
            if validmin is not None:
                df.loc[df[col] < validmin, col] = np.nan
            if validmax is not None:
                df.loc[df[col] > validmax, col] = np.nan

    return {"data": df, "units": units, "description": description, "fill_value": fill_value}


def compute_stats(df: pd.DataFrame) -> dict:
    """Compute per-column summary statistics for a DataFrame.

    Used by both the library API (fetch_data) and the MCP server wrapper.

    Returns:
        Dict keyed by column name with {min, max, mean, std, nan_ratio}.
    """
    stats = {}
    for col in df.columns:
        series = df[col]
        nan_count = int(series.isna().sum())
        total = len(series)
        all_nan = series.isna().all()
        stats[str(col)] = {
            "min": round(float(series.min()), 4) if not all_nan else None,
            "max": round(float(series.max()), 4) if not all_nan else None,
            "mean": round(float(series.mean()), 4) if not all_nan else None,
            "std": round(float(series.std()), 4) if not all_nan else None,
            "nan_ratio": round(nan_count / total, 4) if total > 0 else 0.0,
        }
    return stats


# --- Internal helpers (extracted from xhelio's fetch_cdf.py) ---


def _get_cdf_file_list(dataset_id: str, time_min: str, time_max: str) -> list[dict]:
    """Query CDAWeb REST API for CDF file URLs covering a time range."""
    from cdawebmcp.http import request_with_retry

    start_str = _iso_to_cdaweb_time(time_min)
    stop_str = _iso_to_cdaweb_time(time_max)

    url = f"{CDAWEB_REST_BASE}/datasets/{dataset_id}/orig_data/{start_str},{stop_str}"
    resp = request_with_retry(url, headers={"Accept": "application/json"})
    data = resp.json()

    file_descs = (data.get("FileDescription")
                  or data.get("FileDescriptionList", {}).get("FileDescription")
                  or [])

    if not file_descs:
        raise ValueError(f"No CDF files found for {dataset_id} in {time_min} to {time_max}")

    return [
        {"url": fd.get("Name", ""), "start_time": fd.get("StartTime", ""),
         "end_time": fd.get("EndTime", ""), "size": fd.get("Length", 0)}
        for fd in file_descs if fd.get("Name")
    ]


def _download_and_read(url: str, parameter_id: str, cache_dir: Path):
    """Download a CDF file and read one parameter. Thread-safe."""
    local_path = _download_cdf_file(url, cache_dir)
    data = _read_cdf_parameter(local_path, parameter_id)
    return local_path, data


def _download_cdf_file(url: str, cache_base: Path) -> Path:
    """Download a CDF file, using local cache if available."""
    from cdawebmcp.http import request_with_retry

    parsed = urlparse(url)
    path = parsed.path
    marker = "sp_phys/data/"
    idx = path.find(marker)
    if idx >= 0:
        rel_path = path[idx + len(marker):]
    else:
        rel_path = Path(parsed.path).name

    local_path = cache_base / rel_path

    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path

    logger.info("Downloading: %s", Path(parsed.path).name)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    resp = request_with_retry(url)

    import os
    tmp_path = local_path.with_suffix(".tmp")
    tmp_path.write_bytes(resp.content)
    os.replace(tmp_path, local_path)

    return local_path


def _read_cdf_parameter(cdf_path: Path, parameter_id: str) -> pd.DataFrame:
    """Extract one parameter from a CDF file. Returns DataFrame."""
    import cdflib

    cdf = cdflib.CDF(str(cdf_path))
    info = cdf.cdf_info()

    try:
        param_data = cdf.varget(parameter_id)
    except Exception as e:
        all_vars = info.zVariables + info.rVariables
        raise ValueError(
            f"Variable '{parameter_id}' not found in {cdf_path.name}. Available: {all_vars}"
        ) from e

    # Find epoch variable
    epoch_var = _find_epoch_variable(cdf, info)
    epoch_data = cdf.varget(epoch_var)
    times = cdflib.cdfepoch.to_datetime(epoch_data)

    if param_data.ndim == 1:
        df = pd.DataFrame({1: param_data}, index=times)
    elif param_data.ndim == 2:
        ncols = param_data.shape[1]
        df = pd.DataFrame({i + 1: param_data[:, i] for i in range(ncols)}, index=times)
    else:
        # Flatten higher dimensions for MCP transport
        flat = param_data.reshape(param_data.shape[0], -1)
        ncols = flat.shape[1]
        df = pd.DataFrame({i + 1: flat[:, i] for i in range(ncols)}, index=times)

    df.index.name = "time"
    return df


def _find_epoch_variable(cdf, info) -> str:
    """Find the epoch/time variable in a CDF file."""
    all_vars = info.zVariables + info.rVariables

    for name in ["Epoch", "EPOCH", "epoch", "Epoch1"]:
        if name in all_vars:
            return name

    for var_name in all_vars:
        try:
            var_info = cdf.varinq(var_name)
            if var_info.Data_Type_Description in _EPOCH_TYPES:
                return var_name
        except Exception:
            continue

    raise ValueError(f"No epoch variable found. Variables: {all_vars}")


def _strip_utc_suffix(iso_time: str) -> str:
    """Strip timezone suffix from ISO 8601 string."""
    for suffix in ("+00:00", "+0000", "Z"):
        if iso_time.endswith(suffix):
            return iso_time[:-len(suffix)]
    return iso_time


def _iso_to_cdaweb_time(iso_time: str) -> str:
    """Convert ISO 8601 to CDAWeb REST API format (YYYYMMDDTHHmmSSZ)."""
    t = iso_time
    for suffix in ("+00:00", "+0000"):
        if t.endswith(suffix):
            t = t[:-len(suffix)] + "Z"
            break
    t = t.replace("-", "").replace(":", "")
    if not t.endswith("Z"):
        t += "Z"
    if "T" in t:
        date_part, time_z = t.split("T", 1)
        time_part = time_z.rstrip("Z")
        if "." in time_part:
            time_part = time_part.split(".", 1)[0]
        time_part = time_part[:6].ljust(6, "0")
        t = f"{date_part}T{time_part}Z"
    return t
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_fetch.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/fetch.py tests/test_fetch.py
git commit -m "feat: add CDF data fetching — writes to temp file, returns metadata"
```

---

## Task 7: MCP server (FastMCP)

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/server.py`
- Create: `cdawebmcp/tests/test_server.py`

**Step 1: Write the test**

```python
"""Tests for MCP server tool registration."""
import pytest
from cdawebmcp.server import create_server


def test_server_has_four_tools():
    """Verify all 4 MCP tools are registered."""
    server = create_server()
    # FastMCP stores tools internally — check they exist
    # by checking the server's tool list
    tool_names = [t.name for t in server.list_tools()]
    assert "browse_missions" in tool_names
    assert "load_mission" in tool_names
    assert "browse_parameters" in tool_names
    assert "fetch_data" in tool_names
    assert len(tool_names) == 4
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_server.py -v
```

**Step 3: Write implementation**

```python
"""MCP server — exposes CDAWeb tools via Model Context Protocol."""

import json
import logging
from mcp.server.fastmcp import FastMCP

from cdawebmcp.catalog import browse_missions as _browse_missions, load_mission_json
from cdawebmcp.prompts import build_mission_prompt
from cdawebmcp.metadata import browse_parameters as _browse_parameters
from cdawebmcp.fetch import fetch_data as _fetch_data

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "cdawebmcp",
        version="0.1.0",
        description="MCP server for NASA CDAWeb — browse missions, inspect parameters, fetch heliophysics data",
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
```

**Step 4: Run test**

Note: the test may need adjustment depending on FastMCP's API for listing tools. Check the `mcp` package docs for the correct method.

```bash
python -m pytest tests/test_server.py -v
```

**Step 5: Commit**

```bash
git add src/cdawebmcp/server.py tests/test_server.py
git commit -m "feat: add MCP server with 4 tools — browse_missions, load_mission, browse_parameters, fetch_data"
```

---

## Task 8: Build catalog script

**Files:**
- Create: `cdawebmcp/src/cdawebmcp/scripts/__init__.py`
- Create: `cdawebmcp/src/cdawebmcp/scripts/build_catalog.py`

This script queries CDAWeb's REST API and generates mission JSON files. Extracted from xhelio's `scripts/generate_mission_data.py` + `knowledge/cdaweb_metadata.py` + `knowledge/mission_prefixes.py`.

**Step 1: Write the script**

The script should:
1. Fetch the CDAWeb dataset catalog XML
2. Parse and group datasets by observatory/mission
3. Categorize by InstrumentType
4. Write one JSON per mission to `src/cdawebmcp/data/missions/`

Key functions to extract:
- `fetch_dataset_metadata()` from `knowledge/cdaweb_metadata.py`
- `MISSION_PREFIX_MAP` and `match_dataset_to_mission()` from `knowledge/mission_prefixes.py`
- `INSTRUMENT_TYPE_INFO` and `pick_primary_type()` from `knowledge/cdaweb_metadata.py`
- `update_mission()` from `scripts/generate_mission_data.py`

```python
"""Build the mission catalog from CDAWeb REST API.

Usage:
    python -m cdawebmcp.scripts.build_catalog              # Build all
    python -m cdawebmcp.scripts.build_catalog --mission psp # Build one
"""

# (Full implementation — combine the prefix map, XML parser, and mission builder
#  from xhelio. This is the largest single file. See the source files listed
#  in the design doc for the exact code to extract.)
```

The full implementation should include:
- `MISSION_PREFIX_MAP` (copy from `knowledge/mission_prefixes.py`, CDAWeb entries only — remove PDS URN entries)
- `MISSION_NAMES` (copy from `knowledge/mission_prefixes.py`, CDAWeb entries only)
- `INSTRUMENT_TYPE_INFO` and `INSTRUMENT_TYPE_PRIORITY` (copy from `knowledge/cdaweb_metadata.py`)
- `fetch_cdaweb_catalog()` (adapted from `knowledge/cdaweb_metadata.py:fetch_dataset_metadata()`)
- `build_mission_json()` and `main()` (adapted from `scripts/generate_mission_data.py`)

**Step 2: Run the script to populate missions**

```bash
cd ~/Documents/GitHub/cdawebmcp
python -m cdawebmcp.scripts.build_catalog
```

This will populate `src/cdawebmcp/data/missions/` with all mission JSONs.

**Step 3: Commit**

```bash
git add src/cdawebmcp/scripts/ src/cdawebmcp/data/missions/
git commit -m "feat: add catalog build script and populate mission JSONs from CDAWeb API"
```

---

## Task 9: README and packaging polish

**Files:**
- Modify: `cdawebmcp/README.md`
- Modify: `cdawebmcp/pyproject.toml` (add `[project.optional-dependencies]` for dev)
- Create: `cdawebmcp/.gitignore`
- Create: `cdawebmcp/LICENSE`

**Step 1: Write README**

Cover: what it is, installation (`pip install cdawebmcp`), MCP config JSON, Python library usage, the 4 tools with examples, catalog update instructions.

**Step 2: Add dev dependencies**

```toml
[project.optional-dependencies]
dev = ["pytest", "pytest-cov"]
```

**Step 3: Add .gitignore**

Standard Python .gitignore + `*.cdf`, `~/.cdawebmcp/`.

**Step 4: Add MIT LICENSE**

**Step 5: Commit**

```bash
git add README.md pyproject.toml .gitignore LICENSE
git commit -m "docs: add README, LICENSE, and packaging polish"
```

---

## Task 10: Integration smoke test

**Step 1: Install and run**

```bash
cd ~/Documents/GitHub/cdawebmcp
pip install -e .
python -m cdawebmcp --help 2>/dev/null || python -m cdawebmcp &
```

**Step 2: Test with MCP inspector (if available)**

Or test the Python API directly:

```python
from cdawebmcp.catalog import browse_missions, load_mission_json
from cdawebmcp.prompts import build_mission_prompt
from cdawebmcp.metadata import browse_parameters
from cdawebmcp.fetch import fetch_data

# Test 1: Browse missions
missions = browse_missions()
print(f"Found {len(missions)} missions")
assert len(missions) > 0

# Test 2: Load mission prompt
prompt = build_mission_prompt("ace")
assert "AC_H2_MFI" in prompt
print(f"ACE prompt: {len(prompt)} chars")

# Test 3: Browse parameters (network call)
params = browse_parameters(dataset_id="AC_H2_MFI")
print(f"AC_H2_MFI parameters: {len(params['parameters'])}")

# Test 4: Fetch data (network call) — returns DataFrames directly
result = fetch_data("AC_H2_MFI", ["Magnitude"], "2024-01-01", "2024-01-02")
mag = result["Magnitude"]
print(f"Fetched: {len(mag['data'])} rows, units: {mag['units']}")
print(f"Stats: {mag['stats']}")
assert len(mag["data"]) > 0
assert mag["stats"]["1"]["nan_ratio"] < 1.0  # not all NaN
```

**Step 3: Create GitHub repo and push**

```bash
cd ~/Documents/GitHub/cdawebmcp
gh repo create huangzesen/cdawebmcp --public --source=. --push
```

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: integration fixes from smoke test"
```

---

## Summary

| Task | What | Key files |
|------|------|-----------|
| 1 | Package scaffold | `pyproject.toml`, `__init__.py`, `__main__.py` |
| 2 | HTTP utilities | `http.py` |
| 3 | Mission catalog | `catalog.py` |
| 4 | Prompt assembly | `prompts.py`, `data/prompts/*.md` |
| 5 | Parameter metadata | `metadata.py` |
| 6 | Data fetching | `fetch.py` |
| 7 | MCP server | `server.py` |
| 8 | Build catalog script | `scripts/build_catalog.py` |
| 9 | README + packaging | `README.md`, `LICENSE`, `.gitignore` |
| 10 | Integration test | Smoke test all 4 tools end-to-end |

Tasks 1-7 can be implemented with TDD. Task 8 requires network access. Task 10 validates everything works together.
