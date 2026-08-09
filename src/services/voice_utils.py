import os
import time
import struct
import itertools
import asyncio
from groq import AsyncGroq
from dotenv import load_dotenv
import sys
import httpx
import base64
import re

# Load environment variables
load_dotenv()

# Initialize Groq Client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

_raw_gemini_keys = os.getenv("GEMINI_API_KEY", "")
GEMINI_KEYS = [k.strip() for k in _raw_gemini_keys.split(",") if k.strip()]
key_iterator = itertools.cycle(GEMINI_KEYS) if GEMINI_KEYS else None

# --- START MODIFICATION ---
# VieNeu local/remote HTTP (optional). Edge is latency path; VieNeu races as hot standby.
# Example: VIENEU_TTS_URL=http://127.0.0.1:8022/v1/audio/speech
VIENEU_TTS_URL = (os.getenv("VIENEU_TTS_URL") or "").strip().rstrip("/")
VIENEU_TTS_TIMEOUT_S = float(os.getenv("VIENEU_TTS_TIMEOUT_S") or "20")
VIENEU_VOICE = (os.getenv("VIENEU_VOICE") or "thuc_doan").strip()
EDGE_TTS_TIMEOUT_S = float(os.getenv("EDGE_TTS_TIMEOUT_S") or "12")
# When 1, also race Gemini (legacy). Default 0 — Edge+VieNeu only.
TTS_RACE_GEMINI = (os.getenv("TTS_RACE_GEMINI") or "0").strip() == "1"
# --- END MODIFICATION ---


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wraps raw PCM bytes in a proper WAV header so Android MediaPlayer can play it."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,       # ChunkSize
        b'WAVE',
        b'fmt ',
        16,                   # Subchunk1Size (PCM)
        1,                    # AudioFormat (PCM = 1)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size,
    )
    return header + pcm_data


def _is_vietnamese(text: str, language: str) -> bool:
    return language == "vi" or bool(
        re.search(
            r"[áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]",
            text,
            re.IGNORECASE,
        )
    )


async def _synthesize_edge(text: str, *, is_vietnamese: bool) -> bytes | None:
    """Microsoft Edge neural TTS (fast path)."""
    # --- START MODIFICATION ---
    import edge_tts

    voice = "vi-VN-HoaiMyNeural" if is_vietnamese else "en-US-AriaNeural"
    communicate = edge_tts.Communicate(text, voice)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    if not audio_data:
        return None
    print(f"[Edge TTS] Generated {len(audio_data)} bytes (voice={voice})")
    return bytes(audio_data)
    # --- END MODIFICATION ---


async def _synthesize_vieneu(text: str, *, is_vietnamese: bool) -> bytes | None:
    """
    VieNeu HTTP client (OpenAI-compatible /v1/audio/speech or raw POST).
    Returns None when VIENEU_TTS_URL unset or request fails.
    """
    # --- START MODIFICATION ---
    if not VIENEU_TTS_URL:
        return None
    url = VIENEU_TTS_URL
    if not url.endswith("/speech") and "/v1/" not in url:
        # Allow bare host → OpenAI-compatible path
        url = f"{url}/v1/audio/speech"
    voice = VIENEU_VOICE or ("vi" if is_vietnamese else "en")
    payload = {
        "model": "vieneu",
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }
    async with httpx.AsyncClient(timeout=VIENEU_TTS_TIMEOUT_S) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        ctype = (response.headers.get("content-type") or "").lower()
        data = response.content
        if not data:
            return None
        # Some servers wrap base64 JSON
        if "application/json" in ctype:
            body = response.json()
            b64 = body.get("audio") or body.get("audio_base64") or ""
            if not b64:
                return None
            data = base64.b64decode(b64)
        print(f"[VieNeu TTS] Generated {len(data)} bytes from {url}")
        return data
    # --- END MODIFICATION ---


async def _synthesize_gemini(text: str, *, is_vietnamese: bool) -> bytes | None:
    """Optional Gemini multimodal audio (legacy race participant)."""
    if not GEMINI_KEYS or key_iterator is None:
        return None
    current_key = next(key_iterator)
    voice_name = "Kore" if is_vietnamese else "Aoede"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-preview-tts:generateContent?key={current_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}
            },
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if "inlineData" in part:
                pcm_bytes = base64.b64decode(part["inlineData"]["data"])
                wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate=24000)
                print(f"[Gemini TTS] Generated {len(wav_bytes)} bytes WAV")
                return wav_bytes
    return None


async def synthesize_speech_bytes(
    text: str,
    language: str = "vi",
    force_edge_tts: bool = False,
) -> tuple[bytes | None, int]:
    """
    TTS with parallel hedge:
      - Always start Edge (latency winner).
      - Speculatively start VieNeu when configured (quality standby).
      - Prefer Edge if it succeeds; else take VieNeu (already in flight).
      - force_edge_tts=True → Edge only (dedicated /copilot/tts).
    Returns: (audio_bytes, latency_ms)
    """
    # --- START MODIFICATION ---
    start_time = time.perf_counter()

    if not text.strip():
        return None, int((time.perf_counter() - start_time) * 1000)

    is_vietnamese = _is_vietnamese(text, language)

    if force_edge_tts:
        try:
            audio = await asyncio.wait_for(
                _synthesize_edge(text, is_vietnamese=is_vietnamese),
                timeout=EDGE_TTS_TIMEOUT_S,
            )
            latency = int((time.perf_counter() - start_time) * 1000)
            if audio:
                print(f"[TTS] path=edge_forced ms={latency}")
                return audio, latency
        except Exception as e:
            print(f"[Edge TTS Error]: {e}")
        return None, int((time.perf_counter() - start_time) * 1000)

    async def _edge_job() -> tuple[str, bytes | None]:
        try:
            audio = await asyncio.wait_for(
                _synthesize_edge(text, is_vietnamese=is_vietnamese),
                timeout=EDGE_TTS_TIMEOUT_S,
            )
            return "edge", audio
        except Exception as e:
            print(f"[Edge TTS Error]: {e}")
            return "edge", None

    async def _vieneu_job() -> tuple[str, bytes | None]:
        if not VIENEU_TTS_URL:
            return "vieneu", None
        try:
            audio = await _synthesize_vieneu(text, is_vietnamese=is_vietnamese)
            return "vieneu", audio
        except Exception as e:
            print(f"[VieNeu TTS Error]: {e}")
            return "vieneu", None

    async def _gemini_job() -> tuple[str, bytes | None]:
        try:
            audio = await _synthesize_gemini(text, is_vietnamese=is_vietnamese)
            return "gemini", audio
        except Exception as e:
            print(f"[Gemini TTS Error]: {e}")
            return "gemini", None

    # Race: Edge + VieNeu (+ optional Gemini). Prefer Edge on success.
    tasks = {
        asyncio.create_task(_edge_job(), name="edge"),
        asyncio.create_task(_vieneu_job(), name="vieneu"),
    }
    if TTS_RACE_GEMINI and GEMINI_KEYS:
        tasks.add(asyncio.create_task(_gemini_job(), name="gemini"))

    edge_audio: bytes | None = None
    vieneu_audio: bytes | None = None
    gemini_audio: bytes | None = None
    pending = set(tasks)

    while pending:
        done, pending = await asyncio.wait(
            pending, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            try:
                name, audio = task.result()
            except Exception as e:
                print(f"[TTS race] task failed: {e}")
                continue
            if name == "edge":
                edge_audio = audio
                if audio:
                    # Edge won — cancel speculative jobs
                    for p in pending:
                        p.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    latency = int((time.perf_counter() - start_time) * 1000)
                    print(f"[TTS] path=edge (race win) ms={latency}")
                    return audio, latency
            elif name == "vieneu":
                vieneu_audio = audio
            elif name == "gemini":
                gemini_audio = audio

    # Edge failed/empty — take VieNeu (already finished if raced), else Gemini
    for label, audio in (
        ("vieneu", vieneu_audio),
        ("gemini", gemini_audio),
    ):
        if audio:
            latency = int((time.perf_counter() - start_time) * 1000)
            print(f"[TTS] path={label} (after edge miss) ms={latency}")
            return audio, latency

    latency = int((time.perf_counter() - start_time) * 1000)
    print(f"[TTS] path=none ms={latency}")
    return None, latency
    # --- END MODIFICATION ---


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    filename: str = "input_voice.mp3",
) -> tuple[str, int]:
    """
    Transcribes audio bytes into Vietnamese text using Google's FREE Web Speech API.
    No API Key required! No token limits!
    Returns: (transcribed_text, latency_ms)
    """
    start_time = time.perf_counter()
    if not audio_bytes:
        return "", int((time.perf_counter() - start_time) * 1000)

    try:
        import speech_recognition as sr
        import io

        loop = asyncio.get_event_loop()

        def run_sr():
            recognizer = sr.Recognizer()
            # Recognize using Google Web Speech API (Free, no key required)
            # AudioFile expects PCM WAV (cockpit uploads audio/wav).
            with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
                audio_data = recognizer.record(source)
            return recognizer.recognize_google(audio_data, language="vi-VN")

        transcribed_text = await loop.run_in_executor(None, run_sr)

        latency = int((time.perf_counter() - start_time) * 1000)
        print(f"[Google Free STT] Success! Transcribed: '{transcribed_text}' in {latency}ms")
        return transcribed_text, latency

    # --- START MODIFICATION ---
    # UnknownValueError has empty str(e) — log type so ops can tell silence vs outage.
    except Exception as e:
        import speech_recognition as sr

        latency = int((time.perf_counter() - start_time) * 1000)
        err_name = type(e).__name__
        if isinstance(e, sr.UnknownValueError):
            print(
                f"[Google Free STT] {err_name}: no intelligible speech "
                f"(bytes={len(audio_bytes)}, file={filename!r}) in {latency}ms"
            )
        elif isinstance(e, sr.RequestError):
            print(f"[Google Free STT] {err_name}: API/network failure: {e} in {latency}ms")
        else:
            print(f"[Google Free STT Error] {err_name}: {e!r} (bytes={len(audio_bytes)})")
        return "", latency
    # --- END MODIFICATION ---


if __name__ == "__main__":
    print("==================================================")
    print("TTS RACE: Edge + VieNeu (optional)")
    print("==================================================")

    input_text = "Bật điều hòa 22 độ C"
    print("\n--- Testing synthesize_speech_bytes ---")
    print(f"Synthesizing text: '{input_text}'...")
    audio_bytes, tts_ms = asyncio.run(synthesize_speech_bytes(input_text))

    if audio_bytes:
        print(f"TTS Success! Generated {len(audio_bytes)} bytes audio in {tts_ms}ms.")
        output_filename = "output_test.mp3"
        with open(output_filename, "wb") as f:
            f.write(audio_bytes)
        print(f"Saved audio file locally as '{output_filename}'")
    else:
        print("TTS Failed!")
        sys.exit(1)
