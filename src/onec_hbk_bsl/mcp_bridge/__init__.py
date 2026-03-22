"""BSL MCP server package (FastMCP-based)."""

from __future__ import annotations

__all__ = ["create_mcp_app"]


def __getattr__(name: str):
    # Lazy import: eager `from .server import create_mcp_app` here can interact badly
    # with import order when `mcp` (PyPI) loads alongside our server package (never
    # name a subpackage `mcp` — it can shadow PyPI `mcp`).
    if name == "create_mcp_app":
        from onec_hbk_bsl.mcp_bridge.server import create_mcp_app as _create_mcp_app

        return _create_mcp_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
