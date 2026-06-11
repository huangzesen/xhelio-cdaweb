"""Tests for package configuration and cache path resolution."""
from pathlib import Path

from cdawebmcp import __version__
from cdawebmcp.config import configure, get_cache_root


def test_version_matches_package_metadata():
    """The runtime version should match pyproject.toml for release sanity."""
    assert __version__ == "0.3.7"


def test_cache_root_uses_environment_variable(tmp_path, monkeypatch):
    """XHELIO_CDAWEB_CACHE_DIR should work for MCP registry/env config."""
    configure(None)
    monkeypatch.setenv("XHELIO_CDAWEB_CACHE_DIR", str(tmp_path))
    assert get_cache_root() == tmp_path


def test_configure_overrides_environment_variable(tmp_path, monkeypatch):
    """Explicit configure(cache_dir=...) should have precedence over env var."""
    env_dir = tmp_path / "env"
    explicit_dir = tmp_path / "explicit"
    monkeypatch.setenv("XHELIO_CDAWEB_CACHE_DIR", str(env_dir))
    configure(explicit_dir)
    assert get_cache_root() == explicit_dir
    configure(None)
