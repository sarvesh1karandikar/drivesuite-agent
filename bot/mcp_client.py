"""
DriveSuite — MCP client wrapper (future-proofing).

This module will eventually connect to the mcp-arr containers and
discover tools dynamically.  For now it returns a TODO stub that
is compatible with the tool execution flow.
"""

from __future__ import annotations

import json
from typing import Any


class MCPClient:
    """Minimal MCP client that will later dispatch to remote servers."""

    def __init__(self, server_name: str, base_url: str = "") -> None:
        self.server_name = server_name
        self.base_url = base_url

    async def discover(self) -> list[dict[str, Any]]:
        """Return a list of tool definitions advertised by the server.

        Currently returns a stub list so the agent can wire up tools
        without a running MCP server.
        """
        return [
            {
                "name": "stub_tool",
                "description": f"Stub tool for {self.server_name}",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]

    async def call(
        self,
        server_name: str,
        tool_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call *tool_name* on *server_name* with *params*.

        TODO: Replace with real JSON-RPC over SSE / TCP once the
        mcp-arr containers are deployed.
        """
        _ = params or {}
        return {
            "status": "stub",
            "message": (
                f"MCP call to {server_name}/{tool_name} "
                "is not yet wired to a live server. "
                "Falling back to direct HTTP."
            ),
        }


# Module-level cache of discovered clients (for future use)
_clients: dict[str, MCPClient] = {}


def get_client(server_name: str, base_url: str = "") -> MCPClient:
    """Return a cached MCPClient for *server_name*."""
    if server_name not in _clients:
        _clients[server_name] = MCPClient(server_name, base_url)
    return _clients[server_name]


async def discover_all() -> dict[str, list[dict[str, Any]]]:
    """Discover tools from all configured servers.

    Returns a dict mapping server names to their tool lists.
    """
    results: dict[str, list[dict[str, Any]]] = {}
    for name, client in _clients.items():
        results[name] = await client.discover()
    return results
