"""
DriveSuite — Tool execution functions called by the agent loop.

Each function wraps a conceptual MCP call to a drivesuite-mcp server.
For now these are placeholder HTTP calls to localhost ports matching
the standard arr / media stack ports:
    Sonarr    8989
    Radarr    7878
    Jellyfin  8096
    qBitTorrent  8080
    MeTube    8082

Once the MCP servers are live, each function will use mcp_client instead.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = 15.0  # seconds


async def _http_get(port: int, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Simple GET helper — will be replaced by MCP client calls."""
    url = f"http://localhost:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc), "placeholder": True}


async def _http_post(port: int, path: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Simple POST helper — will be replaced by MCP client calls."""
    url = f"http://localhost:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=json_body or {})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc), "placeholder": True}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def search_movie(query: str) -> str:
    """Search Radarr for *query*.  Returns formatted results."""
    data = await _http_get(7878, "/api/v3/movie", {"term": query})
    if "error" in data:
        return _placeholder(f"Search results for movie: {query}", "Radarr (port 7878)")
    return _radarr_movies_to_text(data)


async def search_series(query: str) -> str:
    """Search Sonarr for *query*.  Returns formatted results."""
    data = await _http_get(8989, "/api/v3/series/lookup", {"term": query})
    if "error" in data:
        return _placeholder(f"Search results for series: {query}", "Sonarr (port 8989)")
    return _sonarr_series_to_text(data)


async def add_movie(
    title: str,
    year: Optional[int] = None,
    tmdb_id: Optional[int] = None,
) -> str:
    """Return a **plan** to add *title* to Radarr.

    Does NOT execute — the agent must wait for user confirmation.
    """
    plan = {
        "action": "add_movie",
        "title": title,
        "year": year,
        "tmdb_id": tmdb_id,
        "source": "Radarr",
    }
    return json.dumps(plan, indent=2)


async def add_series(
    title: str,
    tvdb_id: Optional[int] = None,
) -> str:
    """Return a **plan** to add *title* to Sonarr.

    Does NOT execute — the agent must wait for user confirmation.
    """
    plan = {
        "action": "add_series",
        "title": title,
        "tvdb_id": tvdb_id,
        "source": "Sonarr",
    }
    return json.dumps(plan, indent=2)


async def search_episodes(series_title: str, season_number: Optional[int] = None) -> str:
    """List available episodes for *series_title* (optionally for a specific season)."""
    data = await _http_get(8989, "/api/v3/episode", {"seriesTitle": series_title})
    if "error" in data:
        return _placeholder(
            f"Episodes for {series_title}" + (f" season {season_number}" if season_number else ""),
            "Sonarr (port 8989)",
        )
    return _episodes_to_text(data)


async def download_episode(series_title: str, season: int, episode: int) -> str:
    """Return a **plan** to download a specific episode.

    Does NOT execute — the agent must wait for user confirmation.
    """
    plan = {
        "action": "download_episode",
        "series_title": series_title,
        "season": season,
        "episode": episode,
        "source": "Sonarr / qBittorrent",
    }
    return json.dumps(plan, indent=2)


async def download_season(series_title: str, season: int) -> str:
    """Return a **plan** to download an entire season.

    Does NOT execute — the agent must wait for user confirmation.
    """
    plan = {
        "action": "download_season",
        "series_title": series_title,
        "season": season,
        "source": "Sonarr / qBittorrent",
    }
    return json.dumps(plan, indent=2)


async def youtube(url: str, quality: str = "best") -> str:
    """Return a **plan** to download a YouTube video via MeTube.

    Does NOT execute — the agent must wait for user confirmation.
    """
    plan = {
        "action": "youtube",
        "url": url,
        "quality": quality,
        "source": "MeTube (port 8082)",
    }
    return json.dumps(plan, indent=2)


async def list_downloads() -> str:
    """List active downloads from qBittorrent."""
    data = await _http_get(8080, "/api/v2/torrents/info")
    if "error" in data:
        return _placeholder("Active downloads", "qBittorrent (port 8080)")
    return _torrents_to_text(data)


async def media_status() -> str:
    """Return a summary of the media stack health."""
    results: list[str] = []
    services = [
        ("Radarr", 7878),
        ("Sonarr", 8989),
        ("Jellyfin", 8096),
        ("qBittorrent", 8080),
        ("MeTube", 8082),
    ]
    for name, port in services:
        data = await _http_get(port, "/api/v3/system/status" if name in ("Radarr", "Sonarr") else "/health")
        if "error" in data:
            results.append(f"{name}: unreachable")
        else:
            results.append(f"{name}: online")

    return "\n".join(results) if results else "All services unreachable (this is expected — placeholder mode)."


async def browse_books(query: str) -> str:
    """Browse books (placeholder — no arr integration yet)."""
    # Placeholder: no book arr in the standard stack yet
    return _placeholder(f"Book search for: {query}", "no book server configured")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _radarr_movies_to_text(data: dict[str, Any]) -> str:
    """Format Radarr movie search results into readable text."""
    movies = data if isinstance(data, list) else data.get("records", [])
    if not movies:
        return "No movies found."
    lines = ["**Movie search results:**"]
    for m in movies[:10]:
        title = m.get("title", "Unknown")
        year = m.get("year", "")
        lines.append(f"- {title} ({year})")
    return "\n".join(lines)


def _sonarr_series_to_text(data: dict[str, Any]) -> str:
    """Format Sonarr series search results into readable text."""
    series_list = data if isinstance(data, list) else data.get("records", [])
    if not series_list:
        return "No series found."
    lines = ["**Series search results:**"]
    for s in series_list[:10]:
        title = s.get("title", "Unknown")
        year = s.get("year", "")
        lines.append(f"- {title} ({year})")
    return "\n".join(lines)


def _episodes_to_text(data: dict[str, Any]) -> str:
    """Format episode list into readable text."""
    episodes = data if isinstance(data, list) else data.get("records", [])
    if not episodes:
        return "No episodes found."
    lines = ["**Episodes:**"]
    for ep in episodes[:20]:
        season = ep.get("seasonNumber", "?")
        episode = ep.get("episodeNumber", "?")
        title = ep.get("title", "Untitled")
        lines.append(f"  S{season:02d}E{episode:02d} — {title}")
    return "\n".join(lines)


def _torrents_to_text(data: dict[str, Any]) -> str:
    """Format qBittorrent torrent list into readable text."""
    torrents = data if isinstance(data, list) else data.get("torrents", [])
    if not torrents:
        return "No active downloads."
    lines = ["**Active downloads:**"]
    for t in torrents[:10]:
        name = t.get("name", "Unknown")
        progress = t.get("progress", 0) * 100
        state = t.get("state", "unknown")
        lines.append(f"- {name} — {progress:.0f}% ({state})")
    return "\n".join(lines)


def _placeholder(description: str, server: str) -> str:
    """Return a placeholder response when the real server is unreachable."""
    return (
        f"[PLACEHOLDER] {description}\n"
        f"The {server} server is not yet running. "
        "This message will be replaced by live data once the stack is deployed."
    )


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict[str, callable] = {
    "search_movie": search_movie,
    "search_series": search_series,
    "add_movie": add_movie,
    "add_series": add_series,
    "search_episodes": search_episodes,
    "download_episode": download_episode,
    "download_season": download_season,
    "youtube": youtube,
    "list_downloads": list_downloads,
    "media_status": media_status,
    "browse_books": browse_books,
}


async def execute_tool(tool_name: str, **kwargs: Any) -> str:
    """Execute *tool_name* with *kwargs* and return a human-readable result string.

    Raises ``KeyError`` if the tool is unknown.
    """
    fn = _TOOL_REGISTRY[tool_name]
    return await fn(**kwargs)
