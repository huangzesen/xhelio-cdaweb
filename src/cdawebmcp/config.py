"""Package configuration — centralized settings for cache paths.

Usage:
    import cdawebmcp
    cdawebmcp.configure(cache_dir="/path/to/cache")

Or from internal modules:
    from cdawebmcp.config import get_cache_root
"""

import logging
import shutil
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_cache_dir: Path | None = None
_bootstrapped: bool = False

# Bundled package data directories
_BUNDLED_DATA = Path(__file__).parent / "data"
_BUNDLED_MISSIONS = _BUNDLED_DATA / "missions"
_BUNDLED_METADATA = _BUNDLED_DATA / "metadata"


def configure(cache_dir: str | Path | None = None) -> None:
    """Configure the cdawebmcp package.

    Call once at startup to set the cache root directory. All runtime data
    (metadata cache, CDF file cache, validation overrides) lives under this root.

    Args:
        cache_dir: Root directory for all caches. Defaults to ~/.cdawebmcp/.
    """
    global _cache_dir, _bootstrapped
    if cache_dir is not None:
        _cache_dir = Path(cache_dir)
    else:
        _cache_dir = None
    _bootstrapped = False


def get_cache_root() -> Path:
    """Return the cache root directory.

    Resolution order:
    1. Value set by configure(cache_dir=...)
    2. Default: ~/.cdawebmcp/

    On first access, copies bundled data (missions + metadata) into the cache
    directory if not already present.
    """
    global _bootstrapped
    root = _cache_dir if _cache_dir is not None else Path.home() / ".cdawebmcp"
    if not _bootstrapped:
        _bootstrapped = True
        _bootstrap(root)
    return root


def _bootstrap(root: Path) -> None:
    """Copy bundled missions and metadata into cache dir if not already present.

    Also kicks off a background refresh of dataset time ranges from CDAWeb
    so that start/stop dates stay current.
    """
    _copy_bundled_dir(_BUNDLED_MISSIONS, root / "missions")
    _copy_bundled_dir(_BUNDLED_METADATA, root / "metadata")
    _refresh_time_ranges_background()


def _refresh_time_ranges_background() -> None:
    """Refresh dataset time ranges from CDAWeb in a background thread."""
    def _run():
        try:
            from cdawebmcp.cache import refresh_time_ranges
            result = refresh_time_ranges()
            updated = result.get("datasets_updated", 0)
            if updated:
                logger.info("Background refresh: updated %d dataset time ranges", updated)
        except Exception as e:
            logger.debug("Background time range refresh failed: %s", e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def _copy_bundled_dir(src: Path, dst: Path) -> None:
    """Copy JSON files from bundled src to dst, skipping files that already exist."""
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src_file in src.glob("*.json"):
        dst_file = dst / src_file.name
        if not dst_file.exists():
            shutil.copy2(src_file, dst_file)
            copied += 1
    if copied:
        logger.info("Bootstrapped %d files from %s to %s", copied, src.name, dst)
