"""TTS parallel race: Edge preferred; VieNeu speculative standby."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services import voice_utils


def test_race_prefers_edge_when_both_succeed(monkeypatch):
    monkeypatch.setattr(voice_utils, "VIENEU_TTS_URL", "http://vieneu.test/v1/audio/speech")

    async def fake_edge(text: str, *, is_vietnamese: bool):
        await asyncio.sleep(0.01)
        return b"EDGE"

    async def fake_vieneu(text: str, *, is_vietnamese: bool):
        await asyncio.sleep(0.2)
        return b"VIENEU"

    monkeypatch.setattr(voice_utils, "_synthesize_edge", fake_edge)
    monkeypatch.setattr(voice_utils, "_synthesize_vieneu", fake_vieneu)
    monkeypatch.setattr(voice_utils, "TTS_RACE_GEMINI", False)

    audio, ms = asyncio.run(
        voice_utils.synthesize_speech_bytes("Bật điều hòa", language="vi")
    )
    assert audio == b"EDGE"
    assert ms < 150


def test_race_uses_vieneu_when_edge_fails(monkeypatch):
    monkeypatch.setattr(voice_utils, "VIENEU_TTS_URL", "http://vieneu.test/v1/audio/speech")

    async def fake_edge(text: str, *, is_vietnamese: bool):
        await asyncio.sleep(0.01)
        raise RuntimeError("edge down")

    async def fake_vieneu(text: str, *, is_vietnamese: bool):
        await asyncio.sleep(0.05)
        return b"VIENEU"

    monkeypatch.setattr(voice_utils, "_synthesize_edge", fake_edge)
    monkeypatch.setattr(voice_utils, "_synthesize_vieneu", fake_vieneu)
    monkeypatch.setattr(voice_utils, "TTS_RACE_GEMINI", False)

    audio, _ms = asyncio.run(
        voice_utils.synthesize_speech_bytes("Bật EPB", language="vi")
    )
    assert audio == b"VIENEU"


def test_force_edge_skips_vieneu(monkeypatch):
    called = {"vieneu": False}

    async def fake_edge(text: str, *, is_vietnamese: bool):
        return b"EDGE_ONLY"

    async def fake_vieneu(text: str, *, is_vietnamese: bool):
        called["vieneu"] = True
        return b"VIENEU"

    monkeypatch.setattr(voice_utils, "_synthesize_edge", fake_edge)
    monkeypatch.setattr(voice_utils, "_synthesize_vieneu", fake_vieneu)

    audio, _ = asyncio.run(
        voice_utils.synthesize_speech_bytes("hello", language="en", force_edge_tts=True)
    )
    assert audio == b"EDGE_ONLY"
    assert called["vieneu"] is False
