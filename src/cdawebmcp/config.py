"""Package configuration — centralized settings for cache paths.

Usage:
    import cdawebmcp
    cdawebmcp.configure(cache_dir="/path/to/cache")

Or from internal modules:
    from cdawebmcp.config import get_cache_root
"""

from pathlib import Path

_cache_dir: Path | None = None


def configure(cache_dir: str | Path | None = None) -> None:
    """Configure the cdawebmcp package.

    Call once at startup to set the cache root directory. All runtime data
    (metadata cache, CDF file cache, validation overrides) lives under this root.

    Args:
        cache_dir: Root directory for all caches. Defaults to ~/.cdawebmcp/.
    """
    global _cache_dir
    if cache_dir is not None:
        _cache_dir = Path(cache_dir)
    else:
        _cache_dir = None


def get_cache_root() -> Path:
    """Return the cache root directory.

    Resolution order:
    1. Value set by configure(cache_dir=...)
    2. Default: ~/.cdawebmcp/
    """
    if _cache_dir is not None:
        return _cache_dir
    return Path.home() / ".cdawebmcp"
