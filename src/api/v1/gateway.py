from typing import Literal

import time
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Form
from pydantic import BaseModel, Field
import httpx
import os
import logging
from services.voice_utils import transcribe_audio_bytes, synthesize_speech_bytes
from services.intent_router import classify_intent_fast
from services.car_controller import get_command_id
import base64

logger = logging.getLogger("backend.orchestrator.gateway")

router = APIRouter(prefix="/api/v1")

# Core AI URL definition (KMS RAG Engine runs on port 8001)
CORE_AI_URL = os.getenv("CORE_AI_URL", "http://localhost:8001/api/v1/search")


def _core_ai_mode_for_intent(intent: str) -> str:
    # --- START MODIFICATION ---
    # FREE_TALK → no RAG; everything else uses rag + distance gate
    if intent == "FREE_TALK":
        return "free_talk"
    return "rag"
    # --- END MODIFICATION ---


def _car_control_response(query: str, command_id: str, language: str = "vi") -> dict:
    # --- START MODIFICATION ---
    if language == "en":
        answer = (
            f"Executing {command_id}. Hardware control mock initiated."
        )
    else:
        answer = (
            f"Đang thực thi {command_id}. Giao diện sẽ hiển thị mô phỏng."
        )
    return {
        "query": query,
        "answer": answer,
        "command_id": command_id,
        "citations": [],
        "status": "success",
    }
    # --- END MODIFICATION ---


# ==========================================
# Pydantic Schemas
# ==========================================
class QueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Search query string for RAG",
        examples=["Làm thế nào để kích hoạt phanh khẩn cấp ADAS?"],
    )
    language: Literal["vi", "en"] = Field(
        default="vi",
        description="UI locale — answer language follows this, not the query language",
    )

class CitationPayload(BaseModel):
    document_id: str = "doc_unk"
    document_name: str = "Unspecified Document"
    section: str = "General"
    page: int = 1
    matched_text: str = ""

class QueryResponse(BaseModel):
    query: str
    answer: str
    audio_base64: str | None = None
    command_id: str | None = None
    citations: list[CitationPayload] = []
    status: str = "success"


def _timeout_soft_response(query: str, language: str = "vi") -> QueryResponse:
    # --- START MODIFICATION ---
    if language == "en":
        answer = (
            "Sorry, the assistant is still warming up. Please ask again in a few seconds."
        )
    else:
        answer = (
            "Xin lỗi, trợ lý đang khởi động chậm. Vui lòng hỏi lại sau vài giây."
        )
    return QueryResponse(
        query=query,
        answer=answer,
        citations=[],
        status="success",
    )
    # --- END MODIFICATION ---


class LatencyMetrics(BaseModel):
    stt_ms: int = 0
    core_ai_ms: int = 0
    tts_ms: int = 0
    total_ms: int = 0
    
class VoiceQueryResponse(BaseModel):
    transcript: str
    answer: str
    audio_base64: str | None = None
    command_id: str | None = None
    citations: list[CitationPayload] = []
    latency: LatencyMetrics

class TtsRequest(BaseModel):
    text: str
    language: str = "vi"

class TtsResponse(BaseModel):
    audio_base64: str | None
    latency_ms: int

# ==========================================
# Router Endpoints
# ==========================================
@router.get("/health")
async def gateway_health():
    return {"status": "ok", "service": "backend-orchestrator-gateway"}


@router.post("/copilot/query", response_model=QueryResponse)
async def route_text_query(payload: QueryRequest, request: Request):
    intent, intent_ms = classify_intent_fast(payload.query)
    mode = _core_ai_mode_for_intent(intent)
    language = payload.language or "vi"
    logger.info(
        f"[Gateway] intent={intent} ({intent_ms}ms) mode={mode} "
        f"language={language} query='{payload.query}'"
    )

    if intent == "CAR_CONTROL":
        cmd_id = get_command_id(payload.query)
        data = _car_control_response(payload.query, command_id=cmd_id, language=language)
        return QueryResponse(
            query=data["query"],
            answer=data["answer"],
            command_id=data["command_id"],
            citations=data["citations"],
            status=data["status"],
        )

    try:
        client: httpx.AsyncClient = request.app.state.http_client
        response = await client.post(
            CORE_AI_URL,
            json={
                "query": payload.query,
                "mode": mode,
                "language": language,
            },
        )
        if response.status_code != 200:
            logger.error(
                f"[Gateway] Core AI upstream error: status={response.status_code}, body={response.text}"
            )
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Core AI returned an error: {response.text}",
            )

        data = response.json()
        
        # Generate TTS audio dynamically
        answer_text = data.get("answer", "No response generated by Core AI.")
        audio_bytes, _ = await synthesize_speech_bytes(answer_text, language=language)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None
        
        return QueryResponse(
            query=data.get("query", payload.query),
            answer=answer_text,
            audio_base64=audio_b64,
            citations=data.get("citations", []),
            status=data.get("status", "success"),
        )

    # --- START MODIFICATION ---
    # Soft timeout: demosafe 200 instead of raw 504
    except httpx.TimeoutException as e:
        logger.exception(f"[Gateway] Timeout connecting to Core AI: {e}")
        return _timeout_soft_response(payload.query, language=language)

    except httpx.RequestError as e:
        logger.exception(f"[Gateway] Request failed connecting to Core AI: {e}")
        raise HTTPException(
            status_code=502,
            detail="Bad Gateway: KMS Core AI service is currently unreachable.",
        )
    # --- END MODIFICATION ---


class SttResponse(BaseModel):
    transcript: str
    latency_ms: int

@router.post("/copilot/tts", response_model=TtsResponse)
async def route_tts(request: TtsRequest):
    audio_bytes, latency = await synthesize_speech_bytes(request.text, language=request.language, force_edge_tts=True)
    base64_str = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None
    return TtsResponse(audio_base64=base64_str, latency_ms=latency)

@router.post("/copilot/stt", response_model=SttResponse)
async def route_stt(file: UploadFile = File(...)):
    audio_content = await file.read()
    if not audio_content:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
    
    transcript, stt_ms = await transcribe_audio_bytes(audio_content, filename=file.filename or "input_voice.mp3")
    if not transcript:
        raise HTTPException(status_code=500, detail="Failed to transcribe audio query.")
        
    return SttResponse(transcript=transcript, latency_ms=stt_ms)

@router.post("/copilot/voice-query", response_model=VoiceQueryResponse)
async def route_voice_query(request: Request, file: UploadFile = File(...), language: str = Form("vi")):
    total_start = time.perf_counter()
    logger.info(f"[Gateway] Received voice query file: name={file.filename}")

    audio_content = await file.read()
    if not audio_content:
        raise HTTPException(
            status_code=400, detail="Uploaded audio file is empty."
        )
    
    transcript, stt_ms = await transcribe_audio_bytes(audio_content, filename=file.filename or "input_voice.mp3")
    if not transcript:
        raise HTTPException(
            status_code=500, detail="Failed to transcribe audio query."
        )
    
    core_ai_start = time.perf_counter()
    intent, intent_ms = classify_intent_fast(transcript)
    mode = _core_ai_mode_for_intent(intent)
    # Use parsed language from form
    logger.info(
        f"[Gateway] voice intent={intent} ({intent_ms}ms) mode={mode} transcript='{transcript}'"
    )

    try:
        if intent == "CAR_CONTROL":
            cmd_id = get_command_id(transcript)
            data = _car_control_response(transcript, command_id=cmd_id, language=language)
            # Make sure Voice flow also returns the command_id in the end
        else:
            client: httpx.AsyncClient = request.app.state.http_client
            response = await client.post(
                CORE_AI_URL,
                json={"query": transcript, "mode": mode, "language": language},
            )
            if response.status_code != 200:
                logger.error(
                    f"[Gateway] Core AI upstream error in voice flow: status={response.status_code}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Core AI failed executing search."
                )
            data = response.json()

        core_ai_ms = int((time.perf_counter() - core_ai_start) * 1000)
        audio_bytes, tts_ms = await synthesize_speech_bytes(data.get("answer", ""), language=language)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None
        total_ms = int((time.perf_counter() - total_start) * 1000)

        return VoiceQueryResponse(
            transcript=transcript,
            answer=data.get("answer", "No response generated by Core AI."),
            audio_base64=audio_b64,
            command_id=data.get("command_id", None),
            citations=data.get("citations", []),
            latency=LatencyMetrics(
                stt_ms=stt_ms,
                core_ai_ms=core_ai_ms,
                tts_ms=tts_ms,
                total_ms=total_ms,
            ),
        )

    except httpx.TimeoutException as e:
        logger.exception(f"[Gateway] Voice flow timeout: {e}")
        soft = _timeout_soft_response(transcript, language=language)
        return VoiceQueryResponse(
            transcript=transcript,
            answer=soft.answer,
            audio_base64=None,
            citations=[],
            latency=LatencyMetrics(
                stt_ms=stt_ms,
                core_ai_ms=0,
                tts_ms=0,
                total_ms=int((time.perf_counter() - total_start) * 1000),
            ),
        )

    except httpx.RequestError as e:
        logger.exception(f"[Gateway] Voice flow connection error: {e}")
        raise HTTPException(
            status_code=502,
            detail="Bad Gateway: KMS Core AI service is currently unreachable.",
        )
    

    
@router.post("/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    # Mock Speech-to-Text translation service
    return {"transcript": "Làm thế nào kích hoạt phanh khẩn cấp ADAS?"}


@router.post("/voice/synthesize")
async def synthesize_speech(text: str):
    # Mock Text-to-Speech synthesis service
    return {"audio_url": "/static/audio/response_123.mp3"}
