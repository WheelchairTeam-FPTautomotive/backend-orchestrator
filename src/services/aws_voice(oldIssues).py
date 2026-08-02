import os
import time
import uuid
import boto3
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "automotive-hackathon-wheelchair")

# Configure Boto3 clients
aws_config = Config(
    connect_timeout=2,
    read_timeout=10,
    retries={'max_attempts': 1}
)

try:
    polly_client = boto3.client('polly', region_name=REGION, config=aws_config)
    transcribe_client = boto3.client('transcribe', region_name=REGION, config=aws_config)
    s3_client = boto3.client('s3', region_name=REGION, config=aws_config)
except Exception as e:
    print(f"[AWS Voice] Error initializing AWS clients: {e}")
    polly_client = None
    transcribe_client = None
    s3_client = None


def synthesize_speech(text: str) -> tuple[bytes | None, int]:
    """
    Converts text to Vietnamese speech audio using Amazon Polly.
    Returns: (audio_bytes, latency_ms)
    """
    start_time = time.perf_counter()

    if not polly_client or not text.strip():
        return None, int((time.perf_counter() - start_time) * 1000)

    try:
        response = polly_client.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            # VoiceId="Thanh",       # Standard Vietnamese neural voice
            VoiceId="Joanna",     
            Engine="neural",
            # LanguageCode="vi-VN",
            LanguageCode="en-US"
        )

        audio_stream = response.get("AudioStream")
        if audio_stream:
            audio_bytes = audio_stream.read()
            latency = int((time.perf_counter() - start_time) * 1000)
            return audio_bytes, latency

    except (BotoCoreError, ClientError) as e:
        print(f"[AWS Polly] Synthesis error: {e}")
    except Exception as e:
        print(f"[AWS Polly] Unexpected error: {e}")

    latency = int((time.perf_counter() - start_time) * 1000)
    return None, latency


def transcribe_audio_file(audio_bytes: bytes, file_format: str = "mp3") -> tuple[str, int]:
    """
    Transcribes Vietnamese audio bytes to text using Amazon Transcribe.
    Requires an S3 bucket configured in AWS.
    Returns: (transcribed_text, latency_ms)
    """
    start_time = time.perf_counter()

    if not transcribe_client or not s3_client or not audio_bytes:
        return "", int((time.perf_counter() - start_time) * 1000)

    job_id = f"transcribe_{uuid.uuid4().hex[:8]}"
    s3_key = f"transcribe_input/{job_id}.{file_format}"
    
    try:
        # 1. Upload audio bytes to S3
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=audio_bytes,
            ContentType=f"audio/{file_format}"
        )
        media_uri = f"s3://{S3_BUCKET_NAME}/{s3_key}"

        # 2. Start Transcription Job
        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_id,
            Media={'MediaFileUri': media_uri},
            MediaFormat=file_format,
            LanguageCode='vi-VN'
        )

        # 3. Poll for Completion (Max 15 seconds)
        max_wait = 15
        poll_interval = 0.5
        waited = 0.0

        while waited < max_wait:
            status = transcribe_client.get_transcription_job(TranscriptionJobName=job_id)
            job_status = status['TranscriptionJob']['TranscriptionJobStatus']

            if job_status == 'COMPLETED':
                transcript_file_uri = status['TranscriptionJob']['Transcript']['TranscriptFileUri']
                res = requests.get(transcript_file_uri, timeout=5)
                transcript_data = res.json()
                
                # Extract text
                transcribed_text = (
                    transcript_data.get('results', {})
                    .get('transcripts', [{}])[0]
                    .get('transcript', '')
                )
                
                # Clean up S3 object
                s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
                
                latency = int((time.perf_counter() - start_time) * 1000)
                return transcribed_text, latency

            elif job_status == 'FAILED':
                print(f"[AWS Transcribe] Job failed: {status['TranscriptionJob'].get('FailureReason')}")
                break

            time.sleep(poll_interval)
            waited += poll_interval

    except (BotoCoreError, ClientError) as e:
        print(f"[AWS Transcribe] Error: {e}")
    except Exception as e:
        print(f"[AWS Transcribe] Unexpected error: {e}")

    # Clean up S3 object on failure
    try:
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
    except Exception:
        pass

    latency = int((time.perf_counter() - start_time) * 1000)
    return "", latency


if __name__ == "__main__":
    print("==================================================")
    print("🚀 AWS VOICE SERVICE INTEGRATION TEST")
    print("==================================================")

    # Step 1: Test Polly TTS
    input_text = "Bật điều hòa 22 độ C"
    print(f"\n--- 1. Testing Amazon Polly (TTS) ---")
    print(f"Synthesizing text: '{input_text}'...")
    audio_bytes, tts_ms = synthesize_speech(input_text)

    if audio_bytes:
        print(f"✅ Polly Success! Generated {len(audio_bytes)} bytes audio in {tts_ms}ms.")
        
        # Save output so you can open/play it locally
        with open("output_test.mp3", "wb") as f:
            f.write(audio_bytes)
        print("📁 Saved generated audio to 'output_test.mp3'")
    else:
        print(f"❌ Polly Failed!")
        exit(1)

    # Step 2: Test Transcribe STT using the generated audio
    print(f"\n--- 2. Testing Amazon Transcribe (STT) ---")
    print("Uploading generated audio to S3 and running transcription job...")
    transcribed_text, stt_ms = transcribe_audio_file(audio_bytes, file_format="mp3")

    if transcribed_text:
        print(f"✅ Transcribe Success in {stt_ms}ms!")
        print(f"   Original Text:    '{input_text}'")
        print(f"   Transcribed Text: '{transcribed_text}'")
    else:
        print(f"❌ Transcribe Failed! (Make sure AWS_S3_BUCKET_NAME in .env exists in your S3 console)")

    print("\n==================================================")