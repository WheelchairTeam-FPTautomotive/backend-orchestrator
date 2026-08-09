#!/usr/bin/env python3
"""
OpenAI-compatible VieNeu TTS server for KMS gateway race fallback.

CPU path (official): VieNeu-TTS v3 Turbo via ONNX (torch-free).
  POST /v1/audio/speech  {input, voice, response_format}
  GET  /health
  GET  /v1/voices

Gateway expects VIENEU_TTS_URL=http://127.0.0.1:8022/v1/audio/speech
"""
from __future__ import annotations

import argparse
import io
import wave
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

SAMPLE_RATE = 48_000

# Map gateway/env slugs → VieNeu preset voice labels (v3 Turbo).
VOICE_ALIASES: dict[str, str] = {
    "truc_ly": "Trúc Ly",
    "trucly": "Trúc Ly",
    "thuc_doan": "Thục Đoan",
    "thucdoan": "Thục Đoan",
    "minh_duc": "Minh Đức",
    "minhduc": "Minh Đức",
    "pham_tuyen": "Phạm Tuyên",
    "phamtuyen": "Phạm Tuyên",
    "vi": "Trúc Ly",
    "en": "Minh Đức",
}

app = FastAPI(title="KMS VieNeu OpenAI TTS", version="1.0.0")
_engine: Any = None


def get_engine():
    global _engine
    if _engine is None:
        from vieneu import Vieneu

        # Official CPU path: v3 Turbo ONNX int8 (no PyTorch).
        _engine = Vieneu(backend="onnx")
    return _engine


def resolve_voice(voice: str | None) -> str | None:
    if not voice:
        return "Trúc Ly"
    key = voice.strip()
    aliased = VOICE_ALIASES.get(key.lower().replace(" ", "_").replace("-", "_"))
    return aliased or key


def float32_to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    pcm = (np.asarray(audio, dtype=np.float32) * 32767.0).clip(-32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class SpeechRequest(BaseModel):
    model: str = "vieneu"
    input: str = Field(..., min_length=1)
    voice: str | None = "Trúc Ly"
    response_format: str = "wav"
    speed: float = 1.0


@app.on_event("startup")
def _warmup() -> None:
    get_engine()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "vieneu-openai", "backend": "onnx-v3turbo"}


@app.get("/v1/voices")
def list_voices() -> dict[str, Any]:
    engine = get_engine()
    voices = []
    for item in engine.list_preset_voices() or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            voices.append({"id": item[1], "name": item[0]})
        else:
            voices.append({"id": str(item), "name": str(item)})
    return {"voices": voices}


@app.post("/v1/audio/speech")
def create_speech(req: SpeechRequest) -> Response:
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="input is required")
    voice = resolve_voice(req.voice)
    try:
        engine = get_engine()
        audio = engine.infer(text, voice=voice)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"VieNeu infer failed: {exc}") from exc

    fmt = (req.response_format or "wav").lower()
    # Gateway accepts raw audio bytes; WAV is universal without ffmpeg.
    # If client insists on mp3 and ffmpeg exists, convert; else return wav.
    wav_bytes = float32_to_wav_bytes(np.asarray(audio, dtype=np.float32))
    if fmt == "mp3":
        try:
            import subprocess

            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    "pipe:0",
                    "-f",
                    "mp3",
                    "pipe:1",
                ],
                input=wav_bytes,
                capture_output=True,
                check=True,
                timeout=60,
            )
            return Response(content=proc.stdout, media_type="audio/mpeg")
        except Exception:
            pass
    return Response(content=wav_bytes, media_type="audio/wav")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8022)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
