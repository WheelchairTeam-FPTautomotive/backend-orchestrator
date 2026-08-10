from __future__ import annotations

from typing import Literal

import time
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Form, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
import os
import logging
from services.voice_utils import transcribe_audio_bytes, synthesize_speech_bytes
from services.intent_router import classify_intent
from services.car_controller import DEFAULT_COMMAND_ID, get_command_id
from services.text_norm import normalize_utterance, normalize_for_routing
from services.automotive_stt_correct import format_fixes
from services.query_cache import QueryCache, query_cache
from services.session_memory import session_memory, ttl_min_to_seconds
import base64

logger = logging.getLogger("backend.orchestrator.gateway")

CACHE_BYPASS_HEADER = "X-Cache-Bypass"


def _latency_header_map(
    *,
    stt_ms: int = 0,
    core_ai_ms: int = 0,
    tts_ms: int = 0,
    total_ms: int = 0,
    intent_ms: int = 0,
    cache_status: str,
) -> dict[str, str]:
    # --- START MODIFICATION ---
    return {
        "X-Latency-STT-Ms": str(stt_ms),
        "X-Latency-Core-AI-Ms": str(core_ai_ms),
        "X-Latency-TTS-Ms": str(tts_ms),
        "X-Latency-Total-Ms": str(total_ms),
        "X-Latency-Intent-Ms": str(intent_ms),
        "X-Cache-Status": cache_status,
    }
    # --- END MODIFICATION ---


def _json_with_headers(payload: QueryResponse | dict, headers: dict[str, str]) -> JSONResponse:
    body = payload.model_dump() if isinstance(payload, BaseModel) else payload
    return JSONResponse(content=body, headers=headers)


def _should_bypass_cache(request: Request, x_cache_bypass: str | None = None) -> bool:
    if not query_cache.enabled:
        return True
    raw = (x_cache_bypass if x_cache_bypass is not None else request.headers.get(CACHE_BYPASS_HEADER, ""))
    return str(raw).strip() == "1"


def _cached_query_response(
    *,
    cached: dict,
    raw_utterance: str,
    intent_ms: int,
    total_start: float,
) -> JSONResponse:
    # --- START MODIFICATION ---
    total_ms = int((time.perf_counter() - total_start) * 1000)
    lat = cached.get("latency") or {}
    body = QueryResponse(
        query=cached.get("query", raw_utterance),
        answer=cached.get("answer", ""),
        audio_base64=None,
        command_id=cached.get("command_id"),
        citations=cached.get("citations") or [],
        status=cached.get("status", "success"),
        latency=LatencyMetrics(
            stt_ms=0,
            core_ai_ms=0,
            tts_ms=int(lat.get("tts_ms") or 0),
            total_ms=total_ms,
        ),
    )
    headers = _latency_header_map(
        intent_ms=intent_ms,
        tts_ms=body.latency.tts_ms if body.latency else 0,
        total_ms=total_ms,
        cache_status="HIT",
    )
    logger.info(f"[Gateway] cache=HIT total_ms={total_ms}")
    return _json_with_headers(body, headers)
    # --- END MODIFICATION ---


def _route_car_control(raw_utterance: str, normalized: str, language: str) -> dict:
    """Resolve command_id on normalized text; warn when unmapped GENERIC."""
    # --- START MODIFICATION ---
    from services.safety import is_unsafe_utterance

    if is_unsafe_utterance(raw_utterance, normalized=normalized):
        return _refused_response(raw_utterance, language=language)
    cmd_id = get_command_id(raw_utterance, normalized=normalized)
    if cmd_id == DEFAULT_COMMAND_ID:
        logger.warning(
            "intent=CAR_CONTROL command_id=GENERIC_CONTROL "
            f"utterance={raw_utterance!r} normalized={normalized!r}"
        )
    return _car_control_response(raw_utterance, command_id=cmd_id, language=language)
    # --- END MODIFICATION ---


def _refused_response(query: str, language: str = "vi") -> dict:
    # --- START MODIFICATION ---
    if language == "en":
        answer = "Request refused for vehicle operational safety reasons."
    else:
        answer = "Yêu cầu bị từ chối vì lý do an toàn vận hành xe."
    return {
        "query": query,
        "answer": answer,
        "command_id": None,
        "citations": [],
        "status": "refused",
    }
    # --- END MODIFICATION ---

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
    # --- START MODIFICATION ---
    # Ephemeral STM: idle TTL presets; 0 = off
    session_id: str | None = Field(
        default=None,
        description="Client session UUID; gateway mints one when STM is on",
    )
    session_ttl_min: Literal[0, 3, 5, 10] | None = Field(
        default=None,
        description="Idle TTL minutes (0/3/5/10); default from SESSION_IDLE_TTL_S",
    )
    # --- END MODIFICATION ---

class CitationPayload(BaseModel):
    document_id: str = "doc_unk"
    document_name: str = "Unspecified Document"
    section: str = "General"
    page: int = 1
    matched_text: str = ""


class LatencyMetrics(BaseModel):
    stt_ms: int = 0
    core_ai_ms: int = 0
    tts_ms: int = 0
    total_ms: int = 0


class QueryResponse(BaseModel):
    query: str
    answer: str
    audio_base64: str | None = None
    command_id: str | None = None
    citations: list[CitationPayload] = []
    status: str = "success"
    # MODIFIED: optional stage timings for cockpit developer-mode footer
    latency: LatencyMetrics | None = None
    # --- START MODIFICATION ---
    handoff: bool = False
    session_id: str | None = None
    session_active: bool = False
    stm_turns: int = 0
    # --- END MODIFICATION ---


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
        latency=None,
    )
    # --- END MODIFICATION ---


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
@router.get(
    "/health",
    tags=["health"],
    summary="Gateway health",
)
async def gateway_health():
    return {"status": "ok", "service": "backend-orchestrator-gateway"}


@router.post(
    "/copilot/query",
    response_model=QueryResponse,
    tags=["copilot"],
    summary="Typed copilot query (language-aware cache)",
    description=(
        "Routes text through intent classification then Core AI RAG or car-control. "
        "Short-TTL in-process cache keyed by normalized query + language + intent. "
        "Send header `X-Cache-Bypass: 1` (or set QUERY_CACHE_TTL_S=0) for golden/benchmarks. "
        "Response headers: X-Cache-Status, X-Latency-*-Ms. JSON `latency` kept for cockpit."
    ),
    responses={
        200: {
            "headers": {
                "X-Cache-Status": {
                    "description": "HIT | MISS | BYPASS",
                    "schema": {"type": "string"},
                },
                "X-Latency-Total-Ms": {
                    "description": "End-to-end gateway time in ms",
                    "schema": {"type": "string"},
                },
                "X-Latency-Core-AI-Ms": {
                    "description": "Upstream Core AI time in ms (0 on HIT/CAR)",
                    "schema": {"type": "string"},
                },
                "X-Latency-TTS-Ms": {
                    "description": "TTS time in ms",
                    "schema": {"type": "string"},
                },
                "X-Latency-Intent-Ms": {
                    "description": "Intent classify time in ms",
                    "schema": {"type": "string"},
                },
                "X-Latency-STT-Ms": {
                    "description": "STT time in ms (0 on text query)",
                    "schema": {"type": "string"},
                },
            }
        }
    },
)
async def route_text_query(
    payload: QueryRequest,
    request: Request,
    x_cache_bypass: str | None = Header(
        default=None,
        alias="X-Cache-Bypass",
        description="Set to `1` to skip cache lookup/store (golden eval / benchmarks).",
    ),
    x_session_reset: str | None = Header(
        default=None,
        alias="X-Session-Reset",
        description="Set to `1` to clear STM before handling this turn.",
    ),
):
    # --- START MODIFICATION ---
    # Ingress: automotive STT term repair → tone-fold → intent (#STT-Correct)
    total_start = time.perf_counter()
    original_utterance = payload.query
    raw_utterance, normalized, stt_fixes = normalize_for_routing(original_utterance)
    if stt_fixes:
        logger.info(
            f"[STT-Correct] raw={original_utterance!r} fixed={format_fixes(stt_fixes)} "
            f"corrected={raw_utterance!r}"
        )
    intent, intent_ms = classify_intent(raw_utterance, normalized=normalized)
    mode = _core_ai_mode_for_intent(intent)
    language = payload.language or "vi"
    bypass = _should_bypass_cache(request, x_cache_bypass)
    cache_key = QueryCache.make_key(normalized, language, intent)

    ttl_s = ttl_min_to_seconds(payload.session_ttl_min)
    reset_stm = str(x_session_reset or "").strip() == "1"
    use_stm = intent in {"RAG_SEARCH", "FREE_TALK"} and ttl_s > 0
    session_id = payload.session_id
    session_active = False
    stm_turns = 0
    conversation_context = ""
    if use_stm:
        session_id, stm_state, session_active = session_memory.get_or_create(
            payload.session_id,
            ttl_s=ttl_s,
            reset=reset_stm,
        )
        conversation_context = session_memory.context_block(stm_state)
        stm_turns = len(stm_state.turns)
    elif reset_stm and payload.session_id:
        session_memory.clear(payload.session_id)
        session_id = payload.session_id

    logger.info(
        f"[Gateway] intent={intent} ({intent_ms}ms) mode={mode} "
        f"language={language} bypass={bypass} stm={use_stm} "
        f"session={session_id!r} turns={stm_turns} query={raw_utterance!r} "
        f"normalized={normalized!r}"
    )

    if not bypass:
        cached = query_cache.get(cache_key)
        if cached is not None:
            return _cached_query_response(
                cached=cached,
                raw_utterance=raw_utterance,
                intent_ms=intent_ms,
                total_start=total_start,
            )

    if intent == "REFUSED":
        data = _refused_response(raw_utterance, language=language)
        total_ms = int((time.perf_counter() - total_start) * 1000)
        body = QueryResponse(
            query=data["query"],
            answer=data["answer"],
            command_id=None,
            citations=data["citations"],
            status=data["status"],
            session_id=session_id,
            session_active=False,
            stm_turns=0,
            latency=LatencyMetrics(
                stt_ms=0,
                core_ai_ms=0,
                tts_ms=0,
                total_ms=total_ms,
            ),
        )
        headers = _latency_header_map(
            intent_ms=intent_ms,
            total_ms=total_ms,
            cache_status="BYPASS" if bypass else "MISS",
        )
        logger.info(
            f"[Gateway] intent=REFUSED cache={headers['X-Cache-Status']} "
            f"total_ms={total_ms}"
        )
        return _json_with_headers(body, headers)

    if intent == "CAR_CONTROL":
        data = _route_car_control(raw_utterance, normalized, language)
        total_ms = int((time.perf_counter() - total_start) * 1000)
        body = QueryResponse(
            query=data["query"],
            answer=data["answer"],
            command_id=data.get("command_id"),
            citations=data["citations"],
            status=data["status"],
            session_id=session_id,
            session_active=False,
            stm_turns=0,
            latency=LatencyMetrics(
                stt_ms=0,
                core_ai_ms=0,
                tts_ms=0,
                total_ms=total_ms,
            ),
        )
        headers = _latency_header_map(
            intent_ms=intent_ms,
            total_ms=total_ms,
            cache_status="BYPASS" if bypass else "MISS",
        )
        if not bypass and data["status"] in {"success", "refused"}:
            query_cache.set(cache_key, body.model_dump())
        logger.info(f"[Gateway] cache={headers['X-Cache-Status']} total_ms={total_ms}")
        return _json_with_headers(body, headers)

    try:
        client: httpx.AsyncClient = request.app.state.http_client
        # --- START MODIFICATION ---
        # RC1: warn when Core retrieval is still warming
        try:
            health_url = CORE_AI_URL.replace("/search", "/health")
            hr = await client.get(health_url, timeout=2.0)
            payload_h = hr.json() if hr.headers.get("content-type", "").startswith("application/json") else {}
            if hr.status_code != 200 or (
                isinstance(payload_h, dict)
                and payload_h.get("status") not in {None, "ready", "ok"}
            ):
                logger.warning(
                    "[Gateway] Core AI not ready (status=%s body=%s); RAG may cold-start",
                    hr.status_code,
                    hr.text[:200],
                )
        except Exception as warm_exc:
            logger.warning("[Gateway] Core AI health probe failed: %s", warm_exc)
        # --- END MODIFICATION ---
        core_ai_start = time.perf_counter()
        core_payload: dict = {
            "query": raw_utterance,
            "mode": mode,
            "language": language,
        }
        if conversation_context:
            core_payload["conversation_context"] = conversation_context
        response = await client.post(
            CORE_AI_URL,
            json=core_payload,
        )
        core_ai_ms = int((time.perf_counter() - core_ai_start) * 1000)
        if response.status_code != 200:
            logger.error(
                f"[Gateway] Core AI upstream error: status={response.status_code}, body={response.text}"
            )
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Core AI returned an error: {response.text}",
            )

        data = response.json()

        answer_text = data.get("answer", "No response generated by Core AI.")
        audio_bytes, tts_ms = await synthesize_speech_bytes(answer_text, language=language)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None
        total_ms = int((time.perf_counter() - total_start) * 1000)

        if use_stm and session_id:
            session_memory.append_turn(session_id, "user", raw_utterance)
            session_memory.append_turn(session_id, "assistant", answer_text)
            _, stm_state, _ = session_memory.get_or_create(
                session_id, ttl_s=ttl_s, reset=False
            )
            stm_turns = len(stm_state.turns)
            session_active = stm_turns > 0

        body = QueryResponse(
            query=data.get("query", raw_utterance),
            answer=answer_text,
            audio_base64=audio_b64,
            citations=data.get("citations", []),
            status=data.get("status", "success"),
            # --- START MODIFICATION ---
            handoff=bool(data.get("handoff", False)),
            session_id=session_id,
            session_active=bool(use_stm and session_active),
            stm_turns=stm_turns if use_stm else 0,
            # --- END MODIFICATION ---
            latency=LatencyMetrics(
                stt_ms=0,
                core_ai_ms=core_ai_ms,
                tts_ms=tts_ms,
                total_ms=total_ms,
            ),
        )
        cache_status = "BYPASS" if bypass else "MISS"
        if not bypass and body.status in {"success", "not_found", "refused"}:
            query_cache.set(cache_key, body.model_dump())
        headers = _latency_header_map(
            core_ai_ms=core_ai_ms,
            tts_ms=tts_ms,
            intent_ms=intent_ms,
            total_ms=total_ms,
            cache_status=cache_status,
        )
        logger.info(
            f"[Gateway] cache={cache_status} core_ai_ms={core_ai_ms} "
            f"tts_ms={tts_ms} total_ms={total_ms}"
        )
        return _json_with_headers(body, headers)
        # --- END MODIFICATION ---

    # --- START MODIFICATION ---
    # Soft timeout: demosafe 200 instead of raw 504
    except httpx.TimeoutException as e:
        logger.exception(f"[Gateway] Timeout connecting to Core AI: {e}")
        soft = _timeout_soft_response(raw_utterance, language=language)
        total_ms = int((time.perf_counter() - total_start) * 1000)
        headers = _latency_header_map(
            intent_ms=intent_ms,
            total_ms=total_ms,
            cache_status="BYPASS",
        )
        return _json_with_headers(soft, headers)

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

@router.post("/copilot/tts", response_model=TtsResponse, tags=["voice"], summary="Text-to-speech")
async def route_tts(request: TtsRequest):
    audio_bytes, latency = await synthesize_speech_bytes(request.text, language=request.language, force_edge_tts=True)
    base64_str = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None
    return TtsResponse(audio_base64=base64_str, latency_ms=latency)

@router.post("/copilot/stt", response_model=SttResponse, tags=["voice"], summary="Speech-to-text")
async def route_stt(
    file: UploadFile = File(...),
    # MODIFIED: UI locale from cockpit (vi|en) → Google vi-VN|en-US
    language: str = Form("vi"),
):
    audio_content = await file.read()
    if not audio_content:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    transcript, stt_ms = await transcribe_audio_bytes(
        audio_content,
        filename=file.filename or "input_voice.mp3",
        language=language,
    )
    # --- START MODIFICATION ---
    # Empty transcript = Google could not understand (not a server crash).
    if not transcript:
        raise HTTPException(
            status_code=422,
            detail=(
                "STT could not understand the audio (silence, too short, or noisy). "
                "Retry with a clearer utterance."
            ),
        )
    # --- END MODIFICATION ---

    return SttResponse(transcript=transcript, latency_ms=stt_ms)

@router.post(
    "/copilot/voice-query",
    response_model=VoiceQueryResponse,
    tags=["voice"],
    summary="Voice upload → STT → intent → RAG/control → TTS",
)
async def route_voice_query(request: Request, file: UploadFile = File(...), language: str = Form("vi")):
    total_start = time.perf_counter()
    logger.info(f"[Gateway] Received voice query file: name={file.filename}")

    audio_content = await file.read()
    if not audio_content:
        raise HTTPException(
            status_code=400, detail="Uploaded audio file is empty."
        )
    
    transcript, stt_ms = await transcribe_audio_bytes(
        audio_content,
        filename=file.filename or "input_voice.mp3",
        language=language,
    )
    if not transcript:
        raise HTTPException(
            status_code=500, detail="Failed to transcribe audio query."
        )

    core_ai_start = time.perf_counter()
    # --- START MODIFICATION ---
    original_utterance = transcript
    raw_utterance, normalized, stt_fixes = normalize_for_routing(original_utterance)
    if stt_fixes:
        logger.info(
            f"[STT-Correct] raw={original_utterance!r} fixed={format_fixes(stt_fixes)} "
            f"corrected={raw_utterance!r}"
        )
    intent, intent_ms = classify_intent(raw_utterance, normalized=normalized)
    mode = _core_ai_mode_for_intent(intent)
    logger.info(
        f"[Gateway] voice intent={intent} ({intent_ms}ms) mode={mode} "
        f"transcript={original_utterance!r} corrected={raw_utterance!r} "
        f"normalized={normalized!r}"
    )

    try:
        # --- START MODIFICATION ---
        if intent == "REFUSED":
            data = _refused_response(raw_utterance, language=language)
        elif intent == "CAR_CONTROL":
            data = _route_car_control(raw_utterance, normalized, language)
        else:
            client: httpx.AsyncClient = request.app.state.http_client
            response = await client.post(
                CORE_AI_URL,
                json={"query": raw_utterance, "mode": mode, "language": language},
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
        # --- END MODIFICATION ---

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
