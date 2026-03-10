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


def test_compute_stats():
    """Test per-column statistics computation."""
    from cdawebmcp.fetch import compute_stats

    df = pd.DataFrame({
        "col1": [1.0, 2.0, 3.0, np.nan],
        "col2": [10.0, 20.0, 30.0, 40.0],
    })
    stats = compute_stats(df)
    assert stats["col1"]["min"] == 1.0
    assert stats["col1"]["max"] == 3.0
    assert stats["col1"]["nan_ratio"] == 0.25
    assert stats["col2"]["nan_ratio"] == 0.0


def test_iso_to_cdaweb_time():
    """Test ISO 8601 → CDAWeb REST API time format conversion."""
    from cdawebmcp.fetch import _iso_to_cdaweb_time

    assert _iso_to_cdaweb_time("2024-01-01") == "20240101T000000Z"
    assert _iso_to_cdaweb_time("2024-01-01T12:30:00") == "20240101T123000Z"
    assert _iso_to_cdaweb_time("2024-01-01T12:30:00Z") == "20240101T123000Z"
    assert _iso_to_cdaweb_time("2024-01-01T12:30:00+00:00") == "20240101T123000Z"
