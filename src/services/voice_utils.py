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
    language: str = "vi"
) -> tuple[bytes | None, int]:
    """
    Synthesizes natural text using Gemini Multimodal Audio API.
    Returns: (wav_audio_bytes, latency_ms)
    """
    start_time = time.perf_counter()

    if not text.strip():
        return None, int((time.perf_counter() - start_time) * 1000)

    if not GEMINI_KEYS:
        print("[Gemini TTS Error] No GEMINI_API_KEY found in .env!")
        return None, int((time.perf_counter() - start_time) * 1000)

    current_key = next(key_iterator)

    # Auto-detect language: if text contains Vietnamese diacritics, use Kore (VI), else use Aoede (EN)
    is_vietnamese = bool(re.search(r"[áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]", text, re.IGNORECASE))
    voice_name = "Kore" if is_vietnamese else "Aoede"

    # Call Gemini directly
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={current_key}"
    
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name
                    }
                }
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"[Gemini TTS] Requesting voice='{voice_name}' via direct Google API...")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            candidates = data.get("candidates", [])
            if not candidates:
                print(f"[Gemini TTS Error] No candidates in response: {data}")
                return None, int((time.perf_counter() - start_time) * 1000)
            
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    mime_type = part["inlineData"].get("mimeType", "")
                    audio_b64 = part["inlineData"]["data"]
                    pcm_bytes = base64.b64decode(audio_b64)
                    
                    # Gemini returns raw PCM (Linear16, 24kHz, mono)
                    # Wrap in WAV header so Android MediaPlayer can decode it
                    wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate=24000)
                    
                    latency = int((time.perf_counter() - start_time) * 1000)
                    print(f"[Gemini TTS] Success! Generated {len(wav_bytes)} bytes WAV in {latency}ms (mime={mime_type})")
                    return wav_bytes, latency
                    
            print(f"[Gemini TTS Error] No inlineData found in parts: {parts}")
            return None, int((time.perf_counter() - start_time) * 1000)
    except Exception as e:
        print(f"[Gemini TTS Error]: {e}")
        return None, int((time.perf_counter() - start_time) * 1000)


async def transcribe_audio_bytes(
    audio_bytes: bytes, 
    filename: str = "input_voice.mp3"
) -> tuple[str, int]:
    """
    Transcribes audio bytes into Vietnamese text using Groq's ultra-fast Whisper API.
    Returns: (transcribed_text, latency_ms)
    """
    start_time = time.perf_counter()

    if not groq_client:
        print("[Groq STT Error] GROQ_API_KEY not found in .env!")
        return "", int((time.perf_counter() - start_time) * 1000)

    if not audio_bytes:
        return "", int((time.perf_counter() - start_time) * 1000)

    try:
        # Send raw audio tuple directly from memory to Groq API
        transcription = await groq_client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-large-v3-turbo",  # Ultra-fast, highly accurate
            response_format="json",
            temperature=0.0
        )

        transcribed_text = transcription.text.strip()
        latency = int((time.perf_counter() - start_time) * 1000)
        return transcribed_text, latency

    except Exception as e:
        print(f"[Groq Transcribe Error]: {e}")
        latency = int((time.perf_counter() - start_time) * 1000)
        return "", latency


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