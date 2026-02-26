"""
In-memory activity log for dashboard. Append-only; last N entries kept.
Bot and API can push events; dashboard reads via API.
Bot heartbeat: run_bot.py calls heartbeat() so dashboard can show Running/Stopped.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, List

_MAX = 500
_entries: List[dict] = []
_lock = threading.Lock()
_LOG_PATH = Path(__file__).resolve().parent / "data" / "activity_log.jsonl"

# Bot status: last heartbeat timestamp (Unix); None = never seen
_last_heartbeat: float | None = None
_HEARTBEAT_MAX_AGE = 90  # seconds; if older, consider bot stopped


def push(kind: str, message: str, data: dict | None = None) -> None:
    with _lock:
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "kind": kind,
            "message": message,
            **(data or {}),
        }
        _entries.append(entry)
        if len(_entries) > _MAX:
            _entries.pop(0)
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


def get_all(limit: int = 100) -> List[dict]:
    with _lock:
        return list(_entries[-limit:])[::-1]


def heartbeat() -> None:
    """Call from run_bot.py main loop so dashboard shows 'Trading: Running'."""
    global _last_heartbeat
    with _lock:
        _last_heartbeat = time.time()


def get_bot_status() -> dict:
    """Returns { running: bool, last_heartbeat: str | null } for /api/bot-status."""
    with _lock:
        t = _last_heartbeat
    if t is None:
        return {"running": False, "last_heartbeat": None}
    now = time.time()
    running = (now - t) <= _HEARTBEAT_MAX_AGE
    iso = datetime.utcfromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"running": running, "last_heartbeat": iso}
