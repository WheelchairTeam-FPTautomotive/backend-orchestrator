"""Ephemeral short-term chat memory for gateway (privacy-first STM).

In-process only — pin Uvicorn to 1 worker so sessions stay coherent.
Do not persist to disk or vectorize chat turns.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# --- START MODIFICATION ---
DEFAULT_TTL_S = 300  # 5 minutes
MAX_TURNS = 6
ALLOWED_TTL_MIN: frozenset[int] = frozenset({0, 3, 5, 10})
CONTEXT_CHAR_CAP = 1500


def _default_ttl_from_env() -> int:
    raw = os.getenv("SESSION_IDLE_TTL_S", str(DEFAULT_TTL_S))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_S


def ttl_min_to_seconds(ttl_min: int | None) -> int:
    """Map request preset to seconds; None → env default."""
    if ttl_min is None:
        return _default_ttl_from_env()
    if ttl_min not in ALLOWED_TTL_MIN:
        return _default_ttl_from_env()
    return int(ttl_min) * 60


@dataclass
class SessionTurn:
    role: str  # user | assistant
    text: str
    ts: float = field(default_factory=time.time)


@dataclass
class SessionState:
    turns: list[SessionTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    ttl_s: int = DEFAULT_TTL_S


class SessionMemoryStore:
    """In-memory idle-TTL session store (max 6 turns)."""

    def __init__(self, *, default_ttl_s: int | None = None) -> None:
        self._lock = threading.Lock()
        self._default_ttl_s = (
            _default_ttl_from_env() if default_ttl_s is None else max(0, default_ttl_s)
        )
        self._sessions: dict[str, SessionState] = {}

    @property
    def default_ttl_s(self) -> int:
        return self._default_ttl_s

    def enabled(self, ttl_s: int) -> bool:
        return ttl_s > 0

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

    def clear(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def _expired(self, state: SessionState, now: float) -> bool:
        if state.ttl_s <= 0:
            return True
        return (now - state.last_active) > state.ttl_s

    def get_or_create(
        self,
        session_id: str | None,
        *,
        ttl_s: int,
        reset: bool = False,
    ) -> tuple[str, SessionState, bool]:
        """
        Returns (session_id, state, active).
        active=False when STM off (ttl_s=0) or after idle wipe with empty turns.
        """
        if not self.enabled(ttl_s):
            sid = session_id or self.new_session_id()
            return sid, SessionState(ttl_s=0), False

        sid = (session_id or "").strip() or self.new_session_id()
        now = time.time()
        with self._lock:
            if reset:
                self._sessions.pop(sid, None)
            state = self._sessions.get(sid)
            if state is None or self._expired(state, now):
                state = SessionState(ttl_s=ttl_s, last_active=now)
                self._sessions[sid] = state
                return sid, state, False
            state.ttl_s = ttl_s
            return sid, state, len(state.turns) > 0

    def touch(self, session_id: str) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                state.last_active = time.time()

    def append_turn(self, session_id: str, role: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not session_id or not cleaned:
            return
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None or state.ttl_s <= 0:
                return
            state.turns.append(SessionTurn(role=role, text=cleaned[:800]))
            if len(state.turns) > MAX_TURNS:
                state.turns = state.turns[-MAX_TURNS:]
            state.last_active = time.time()

    def context_block(self, state: SessionState) -> str:
        """Compact prior transcript for Core (excludes current turn)."""
        if not state.turns:
            return ""
        lines: list[str] = []
        for turn in state.turns:
            label = "Driver" if turn.role == "user" else "Assistant"
            lines.append(f"{label}: {turn.text}")
        blob = "\n".join(lines)
        if len(blob) > CONTEXT_CHAR_CAP:
            blob = blob[-CONTEXT_CHAR_CAP:]
        return blob

    def snapshot(self, state: SessionState) -> dict[str, Any]:
        return {
            "stm_turns": len(state.turns),
            "ttl_s": state.ttl_s,
            "last_active": state.last_active,
        }


# Process-wide singleton — requires single Uvicorn worker
session_memory = SessionMemoryStore()
# --- END MODIFICATION ---
