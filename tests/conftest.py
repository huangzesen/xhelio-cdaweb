"""Shared test fixtures."""
import pytest


@pytest.fixture(autouse=True)
def skip_bootstrap(monkeypatch):
    """Skip bootstrap in tests by default.

    Tests that monkeypatch _cache_dir to tmp_path don't want bundled data
    copied in. Setting _bootstrapped=True prevents get_cache_root() from
    running _bootstrap().
    """
    monkeypatch.setattr("cdawebmcp.config._bootstrapped", True)
