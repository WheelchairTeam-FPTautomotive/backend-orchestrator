"""Language-aware query cache + gateway headers (#16)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.query_cache import QueryCache, query_cache
from services.text_norm import normalize_utterance


@pytest.fixture(autouse=True)
def _isolate_process_cache() -> Iterator[None]:
    query_cache.clear()
    yield
    query_cache.clear()


def test_make_key_isolates_language_and_intent() -> None:
    n = normalize_utterance("Làm sao để kiểm tra phanh?")
    k_vi = QueryCache.make_key(n, "vi", "RAG_SEARCH")
    k_en = QueryCache.make_key(n, "en", "RAG_SEARCH")
    k_car = QueryCache.make_key(n, "vi", "CAR_CONTROL")
    assert k_vi != k_en
    assert k_vi != k_car


def test_set_strips_audio_base64() -> None:
    cache = QueryCache(ttl_s=60, maxsize=16)
    key = QueryCache.make_key("mo cua", "vi", "CAR_CONTROL")
    cache.set(
        key,
        {
            "query": "mo cua",
            "answer": "ok",
            "audio_base64": "AAAA" * 1000,
            "status": "success",
        },
    )
    hit = cache.get(key)
    assert hit is not None
    assert hit["audio_base64"] is None
    assert hit["answer"] == "ok"


def test_ttl_zero_disables() -> None:
    cache = QueryCache(ttl_s=0)
    assert not cache.enabled
    key = QueryCache.make_key("x", "vi", "FREE_TALK")
    cache.set(key, {"answer": "nope"})
    assert cache.get(key) is None


def test_vi_hit_en_miss_isolation() -> None:
    cache = QueryCache(ttl_s=60)
    n = normalize_utterance("xin chao")
    key_vi = QueryCache.make_key(n, "vi", "FREE_TALK")
    key_en = QueryCache.make_key(n, "en", "FREE_TALK")
    cache.set(key_vi, {"answer": "Xin chào bạn!", "status": "success"})
    assert cache.get(key_vi)["answer"] == "Xin chào bạn!"
    assert cache.get(key_en) is None


@pytest.fixture
def gateway_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, AsyncMock]]:
    import main as main_mod

    async def _fake_tts(text: str, language: str = "vi", force_edge_tts: bool = False):
        return b"", 5

    monkeypatch.setattr("api.v1.gateway.synthesize_speech_bytes", _fake_tts)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "query": "Làm sao để kiểm tra phanh?",
        "answer": "Kiểm tra phanh theo hướng dẫn OEM.",
        "citations": [],
        "status": "success",
    }
    mock_post = AsyncMock(return_value=mock_response)

    with TestClient(main_mod.app) as client:
        monkeypatch.setattr(client.app.state.http_client, "post", mock_post)
        yield client, mock_post


def test_gateway_vi_hit_en_miss_and_bypass(
    gateway_client: tuple[TestClient, AsyncMock],
) -> None:
    client, mock_post = gateway_client
    body = {"query": "Làm sao để kiểm tra phanh?", "language": "vi"}

    r1 = client.post("/api/v1/copilot/query", json=body)
    assert r1.status_code == 200
    assert r1.headers.get("X-Cache-Status") == "MISS"
    assert "X-Latency-Total-Ms" in r1.headers
    assert r1.json()["latency"] is not None
    assert mock_post.await_count == 1

    r2 = client.post("/api/v1/copilot/query", json=body)
    assert r2.status_code == 200
    assert r2.headers.get("X-Cache-Status") == "HIT"
    assert r2.json()["answer"] == r1.json()["answer"]
    assert r2.json()["audio_base64"] is None
    assert mock_post.await_count == 1

    r_en = client.post(
        "/api/v1/copilot/query",
        json={"query": "Làm sao để kiểm tra phanh?", "language": "en"},
    )
    assert r_en.status_code == 200
    assert r_en.headers.get("X-Cache-Status") == "MISS"
    assert mock_post.await_count == 2

    r_bypass = client.post(
        "/api/v1/copilot/query",
        json=body,
        headers={"X-Cache-Bypass": "1"},
    )
    assert r_bypass.status_code == 200
    assert r_bypass.headers.get("X-Cache-Status") == "BYPASS"
    assert mock_post.await_count == 3


def test_gateway_car_control_headers(
    gateway_client: tuple[TestClient, AsyncMock],
) -> None:
    client, mock_post = gateway_client
    r1 = client.post(
        "/api/v1/copilot/query",
        json={"query": "open the door", "language": "en"},
    )
    assert r1.status_code == 200
    assert r1.headers.get("X-Cache-Status") == "MISS"
    assert r1.json()["command_id"] == "DOOR_OPEN"
    assert mock_post.await_count == 0

    r2 = client.post(
        "/api/v1/copilot/query",
        json={"query": "open the door", "language": "en"},
    )
    assert r2.headers.get("X-Cache-Status") == "HIT"
    assert r2.json()["command_id"] == "DOOR_OPEN"
