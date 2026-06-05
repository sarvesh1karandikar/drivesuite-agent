"""
DriveSuite — SQLite-backed per-user conversation state machine.

States:
    IDLE                   — awaiting user input
    BROWSING               — user is reviewing search results
    AWAITING_CONFIRMATION  — a destructive action needs explicit approval
    DOWNLOADING            — a download is in progress
    DONE                   — the last operation completed

Every destructive tool (download, add, delete) is gated by state:
it may only be invoked when the state is AWAITING_CONFIRMATION.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Enum-like state constants
# ---------------------------------------------------------------------------

IDLE = "IDLE"
BROWSING = "BROWSING"
AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
DOWNLOADING = "DOWNLOADING"
DONE = "DONE"

ALL_STATES = frozenset({IDLE, BROWSING, AWAITING_CONFIRMATION, DOWNLOADING, DONE})

# Map each tool name to the state in which it is allowed.
# Tools not listed here are allowed in any state.
_DESTRUCTIVE_TOOLS = frozenset({
    "add_movie",
    "add_series",
    "download_episode",
    "download_season",
})

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_db_path: Optional[Path] = None
_local = threading.local()


def _get_db() -> sqlite3.Connection:
    """Return a thread-local connection to the SQLite database."""
    if not hasattr(_local, "conn") or _local.conn is None:
        path = _db_path or Path.home() / ".drivesuite" / "conversations.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(path))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _init_db(_local.conn)
    return _local.conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            user_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'IDLE',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pending_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pending_confirmations (
            user_id INTEGER PRIMARY KEY,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def configure_database(path: str | Path) -> None:
    """Set a custom database path before any state calls."""
    global _db_path
    _db_path = Path(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_state(user_id: int) -> str:
    """Return the current conversation state for *user_id*."""
    conn = _get_db()
    row = conn.execute(
        "SELECT state FROM conversations WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO conversations (user_id, state) VALUES (?, ?)",
            (user_id, IDLE),
        )
        conn.commit()
        return IDLE
    return row["state"]


def set_state(
    user_id: int,
    state: str,
    pending_plan: Optional[str] = None,
) -> None:
    """Set the conversation state and optionally attach a pending download plan."""
    assert state in ALL_STATES, f"Invalid state: {state}"

    conn = _get_db()
    conn.execute(
        """INSERT INTO conversations (user_id, state, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
               state = excluded.state,
               updated_at = excluded.updated_at""",
        (user_id, state),
    )

    if pending_plan is not None:
        conn.execute(
            """INSERT INTO pending_confirmations (user_id, plan_json, created_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   plan_json = excluded.plan_json,
                   created_at = excluded.created_at""",
            (user_id, pending_plan),
        )

    conn.commit()


def get_pending_plan(user_id: int) -> Optional[str]:
    """Return the JSON plan string awaiting confirmation, or *None*."""
    conn = _get_db()
    row = conn.execute(
        "SELECT plan_json FROM pending_confirmations WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["plan_json"] if row else None


def clear_pending_plan(user_id: int) -> None:
    """Remove the saved plan once it has been acted on or discarded."""
    conn = _get_db()
    conn.execute("DELETE FROM pending_confirmations WHERE user_id = ?", (user_id,))
    conn.commit()


def can_execute(tool_name: str, state: str) -> bool:
    """Return *True* if *tool_name* may be invoked in *state*.

    Destructive tools require ``AWAITING_CONFIRMATION``.
    Read-only tools are always allowed.
    """
    if tool_name in _DESTRUCTIVE_TOOLS:
        return state == AWAITING_CONFIRMATION
    return True
