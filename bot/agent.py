"""
DriveSuite — LLM interface using the Anthropic SDK pointed at DeepSeek.

Agent loop:
  1. Accept user message + conversation history + current state.
  2. Send the message (with system prompt + tool definitions) to the LLM.
  3. If the response contains tool calls:
       a. Check the state machine: destructive tools are gated.
       b. Execute allowed tools via ``tools.execute_tool()``.
       c. Feed results back to the LLM.
       d. Repeat until ``stop_reason`` is ``"end_turn"``.
  4. Return the final reply + any state transitions.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from anthropic import Anthropic

from bot import state_machine
from bot.tools import execute_tool

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(
            base_url="https://api.deepseek.com/anthropic",
            api_key=os.environ["DEEPSEEK_DRIVESUITE_API_KEY"],
        )
    return _client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are DriveSuite, a personal media assistant. "
    "Before downloading ANYTHING, show the user a plan and wait for confirmation. "
    "Ask clarifying questions. Never assume."
)

# ---------------------------------------------------------------------------
# Tool definitions for the LLM
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_movie",
        "description": "Search for a movie by title. Returns matching results from Radarr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Movie title to search for"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_series",
        "description": "Search for a TV series by title. Returns matching results from Sonarr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Series title to search for"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_movie",
        "description": "Add a movie to Radarr. **Requires confirmation** — returns a plan, does not execute.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Movie title"},
                "year": {"type": "number", "description": "Release year (optional)"},
                "tmdb_id": {"type": "number", "description": "TMDb ID (optional)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "add_series",
        "description": "Add a TV series to Sonarr. **Requires confirmation** — returns a plan, does not execute.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Series title"},
                "tvdb_id": {"type": "number", "description": "TVDB ID (optional)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_episodes",
        "description": "List available episodes for a series, optionally filtered by season.",
        "input_schema": {
            "type": "object",
            "properties": {
                "series_title": {"type": "string", "description": "TV series title"},
                "season_number": {
                    "type": "number",
                    "description": "Season number (optional)",
                },
            },
            "required": ["series_title"],
        },
    },
    {
        "name": "download_episode",
        "description": "Download a specific episode. **Requires confirmation** — returns a plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "series_title": {"type": "string", "description": "TV series title"},
                "season": {"type": "number", "description": "Season number"},
                "episode": {"type": "number", "description": "Episode number"},
            },
            "required": ["series_title", "season", "episode"],
        },
    },
    {
        "name": "download_season",
        "description": "Download an entire season. **Requires confirmation** — returns a plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "series_title": {"type": "string", "description": "TV series title"},
                "season": {"type": "number", "description": "Season number"},
            },
            "required": ["series_title", "season"],
        },
    },
    {
        "name": "youtube",
        "description": "Download a YouTube video via MeTube. **Requires confirmation** — returns a plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube video URL"},
                "quality": {
                    "type": "string",
                    "description": "Video quality (best, 1080p, 720p, etc.)",
                    "default": "best",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "list_downloads",
        "description": "List all active downloads from qBittorrent.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "media_status",
        "description": "Check the health / availability of all media services (Radarr, Sonarr, Jellyfin, qBittorrent, MeTube).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "browse_books",
        "description": "Search for books. Returns placeholder results — no book server configured yet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Book title or author to search for"}
            },
            "required": ["query"],
        },
    },
]

# ---------------------------------------------------------------------------
# Core agent logic
# ---------------------------------------------------------------------------


def _convert_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convert simple {role, content} history to Anthropic messages format.

    Strips messages with role ``system`` (we inject the system prompt separately).
    """
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg["role"] in ("user", "assistant")
    ]


async def process_message(
    text: str,
    user_id: int,
    conversation_history: list[dict[str, str]],
    current_state: str,
) -> dict[str, Any]:
    """Process a user message and return the assistant's response.

    Returns::

        {
            "reply": str,                     # Final reply text
            "tool_calls": list[dict] | None,  # Tool calls made (for logging)
            "new_state": str,                 # Updated state
        }
    """
    client = _get_client()
    messages = _convert_history(conversation_history) + [
        {"role": "user", "content": text}
    ]

    state = current_state
    tool_calls_made: list[dict[str, Any]] = []

    # Manual tool loop
    while True:
        response = client.messages.create(
            model="deepseek-chat",
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            max_tokens=4096,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input if isinstance(block.input, dict) else {}

                tool_calls_made.append({"name": tool_name, "input": tool_input})

                # Gate destructive tools through state machine
                if not state_machine.can_execute(tool_name, state):
                    result = (
                        f"Cannot execute `{tool_name}` in current state `{state}`. "
                        "A download plan must first be confirmed by the user."
                    )
                else:
                    result = await execute_tool(tool_name, **tool_input)

                # Update state based on the tool
                if tool_name in ("add_movie", "add_series", "download_episode",
                                 "download_season", "youtube"):
                    state_machine.set_state(user_id, state_machine.AWAITING_CONFIRMATION, pending_plan=result)
                    state = state_machine.AWAITING_CONFIRMATION
                    result = (
                        "Here is the download plan:\n\n"
                        f"{result}\n\n"
                        "React with ✅ to confirm or ❌ to cancel."
                    )

                # Feed the tool result back to the LLM
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    ],
                })

            continue  # Continue the tool loop

        # If stop_reason is something else (e.g. max_tokens), treat
        # whatever text the model produced as its final answer.
        break

    # Extract the text from the final response
    reply_parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            reply_parts.append(block.text)

    reply = "".join(reply_parts) if reply_parts else "I'm not sure how to respond."

    # Persist state if it changed during processing
    if state != current_state:
        state_machine.set_state(user_id, state)

    return {
        "reply": reply,
        "tool_calls": tool_calls_made or None,
        "new_state": state,
    }
