"""cdawebmcp — NASA CDAWeb data access for heliophysics.

Install as: pip install xhelio-cdaweb
For MCP server: pip install xhelio-cdaweb[mcp]
"""

__version__ = "0.1.0"

from cdawebmcp.config import configure


def main():
    """Entry point for the MCP server (xhelio-cdaweb-mcp command).

    Requires the [mcp] extra: pip install xhelio-cdaweb[mcp]
    """
    try:
        from cdawebmcp.server import serve
    except ImportError:
        print(
            "Error: MCP server requires the 'mcp' package.\n"
            "Install with: pip install xhelio-cdaweb[mcp]"
        )
        raise SystemExit(1)
    serve()
