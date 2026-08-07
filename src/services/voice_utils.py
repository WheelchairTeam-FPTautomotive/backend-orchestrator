import os
import time
import struct
import itertools
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


async def synthesize_speech_bytes(
    text: str, 
    language: str = "vi",
    force_edge_tts: bool = False
) -> tuple[bytes | None, int]:
    """
    Synthesizes natural text. Tries Gemini Multimodal Audio API first, falls back to Edge TTS.
    Returns: (audio_bytes, latency_ms)
    """
    start_time = time.perf_counter()

    if not text.strip():
        return None, int((time.perf_counter() - start_time) * 1000)

    # Auto-detect language
    is_vietnamese = language == "vi" or bool(re.search(r"[áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]", text, re.IGNORECASE))

    # 1. Try Gemini TTS (if key exists)
    if GEMINI_KEYS and not force_edge_tts:
        try:
            current_key = next(key_iterator)
            voice_name = "Kore" if is_vietnamese else "Aoede"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={current_key}"
            
            payload = {
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}}
                }
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "inlineData" in part:
                            pcm_bytes = base64.b64decode(part["inlineData"]["data"])
                            wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate=24000)
                            latency = int((time.perf_counter() - start_time) * 1000)
                            print(f"[Gemini TTS] Success! Generated {len(wav_bytes)} bytes WAV in {latency}ms")
                            return wav_bytes, latency
        except Exception as e:
            print(f"[Gemini TTS Warning] Failed: {e}. Falling back to Edge TTS...")

    # 2. Fallback to Edge TTS (Free, no key required)
    print("[Edge TTS] Using Microsoft Edge TTS fallback...")
    try:
        import edge_tts
        voice = "vi-VN-HoaiMyNeural" if is_vietnamese else "en-US-AriaNeural"
        
        communicate = edge_tts.Communicate(text, voice)
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
                
        latency = int((time.perf_counter() - start_time) * 1000)
        print(f"[Edge TTS] Success! Generated {len(audio_data)} bytes in {latency}ms (voice={voice})")
        return bytes(audio_data), latency
    except Exception as e:
        print(f"[Edge TTS Error]: {e}")
        return None, int((time.perf_counter() - start_time) * 1000)


async def transcribe_audio_bytes(
    audio_bytes: bytes, 
    filename: str = "input_voice.mp3"
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
        import asyncio
        
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
    print("🚀 GROQ STT + EDGE-TTS PIPELINE TEST")
    print("==================================================")

    # 1. Test Vietnamese TTS
    input_text = "Bật điều hòa 22 độ C"
    print("\n--- 1. Testing edge-tts (TTS) ---")
    print(f"Synthesizing text: '{input_text}'...")
    audio_bytes, tts_ms = synthesize_speech_bytes(input_text)

    if audio_bytes:
        print(f"✅ TTS Success! Generated {len(audio_bytes)} bytes audio in {tts_ms}ms.")
        
        # Save output file so you can listen locally
        output_filename = "output_test.mp3"
        with open(output_filename, "wb") as f:
            f.write(audio_bytes)
        print(f"📁 Saved audio file locally as '{output_filename}'")
    else:
        print("❌ TTS Failed!")
        sys.exit(1)

    # 2. Test Groq STT using the generated audio
    print("\n--- 2. Testing Groq Cloud Whisper (STT) ---")
    print("Sending audio bytes directly to Groq LPU...")
    transcribed_text, stt_ms = transcribe_audio_bytes(audio_bytes, filename="test.mp3")

    if transcribed_text:
        print(f"✅ Transcribe Success in {stt_ms}ms!")
        print(f"   Original Text:    '{input_text}'")
        print(f"   Transcribed Text: '{transcribed_text}'")
    else:
        print("❌ Transcribe Failed! Check your GROQ_API_KEY in .env")

    print("\n==================================================")