import os
import time
import asyncio
import edge_tts
from groq import AsyncGroq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Groq Client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


async def synthesize_speech_bytes(
    text: str, 
    voice: str = "vi-VN-HoaiMyNeural"
) -> tuple[bytes | None, int]:
    """
    Synthesizes natural Vietnamese text using Microsoft Edge Neural TTS.
    Returns: (audio_bytes, latency_ms)
    """
    start_time = time.perf_counter()

    if not text.strip():
        return None, int((time.perf_counter() - start_time) * 1000)

    try:
        communicate = edge_tts.Communicate(text, voice)
        audio_bytes = b""

        # Stream audio chunks directly in memory
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]

        latency = int((time.perf_counter() - start_time) * 1000)
        return audio_bytes, latency

    except Exception as e:
        print(f"[edge-tts Error]: {e}")
        latency = int((time.perf_counter() - start_time) * 1000)
        return None, latency


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
            language="vi",                    # Force Vietnamese language
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
    print(f"\n--- 1. Testing edge-tts (TTS) ---")
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
        print(f"❌ TTS Failed!")
        exit(1)

    # 2. Test Groq STT using the generated audio
    print(f"\n--- 2. Testing Groq Cloud Whisper (STT) ---")
    print("Sending audio bytes directly to Groq LPU...")
    transcribed_text, stt_ms = transcribe_audio_bytes(audio_bytes, filename="test.mp3")

    if transcribed_text:
        print(f"✅ Transcribe Success in {stt_ms}ms!")
        print(f"   Original Text:    '{input_text}'")
        print(f"   Transcribed Text: '{transcribed_text}'")
    else:
        print(f"❌ Transcribe Failed! Check your GROQ_API_KEY in .env")

    print("\n==================================================")