"""Unit tests for ephemeral SessionMemoryStore."""

from __future__ import annotations

import time

from services.session_memory import SessionMemoryStore, ttl_min_to_seconds


def test_ttl_min_mapping():
    assert ttl_min_to_seconds(0) == 0
    assert ttl_min_to_seconds(3) == 180
    assert ttl_min_to_seconds(5) == 300
    assert ttl_min_to_seconds(10) == 600


def test_max_six_turns_and_context():
    store = SessionMemoryStore(default_ttl_s=300)
    sid, state, active = store.get_or_create(None, ttl_s=300)
    assert active is False
    for i in range(8):
        store.append_turn(sid, "user", f"q{i}")
        store.append_turn(sid, "assistant", f"a{i}")
    _, state, active = store.get_or_create(sid, ttl_s=300)
    assert active is True
    assert len(state.turns) == 6
    ctx = store.context_block(state)
    assert "q5" in ctx or "q7" in ctx
    assert "q0" not in ctx


def test_idle_expiry_wipes_history():
    store = SessionMemoryStore(default_ttl_s=1)
    sid, _, _ = store.get_or_create("s1", ttl_s=1)
    store.append_turn(sid, "user", "torque spec")
    store.append_turn(sid, "assistant", "150 Nm")
    time.sleep(1.1)
    _, state, active = store.get_or_create(sid, ttl_s=1)
    assert active is False
    assert state.turns == []


def test_reset_clears_session():
    store = SessionMemoryStore(default_ttl_s=300)
    sid, _, _ = store.get_or_create("s2", ttl_s=300)
    store.append_turn(sid, "user", "hello")
    store.get_or_create(sid, ttl_s=300, reset=True)
    _, state, active = store.get_or_create(sid, ttl_s=300)
    assert active is False
    assert state.turns == []


def test_stm_off_ttl_zero():
    store = SessionMemoryStore(default_ttl_s=0)
    sid, state, active = store.get_or_create("x", ttl_s=0)
    assert active is False
    store.append_turn(sid, "user", "should not store")
    assert state.turns == []
