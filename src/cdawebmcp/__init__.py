"""cdawebmcp — MCP server for NASA CDAWeb data access."""

__version__ = "0.1.0"


def main():
    """Entry point for the cdawebmcp CLI."""
    from cdawebmcp.server import serve
    serve()
