from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List
import requests
import os
import shutil

router = APIRouter(prefix="/api/v1")

# Core AI URL definition (KMS RAG Engine runs on port 8001)
CORE_AI_URL = os.getenv("CORE_AI_URL", "http://localhost:8001/api/v1/search")

# ==========================================
# Pydantic Schemas
# ==========================================
class QueryRequest(BaseModel):
    query: str

class CitationInfo(BaseModel):
    document_id: str
    document_name: str
    section: str
    page: int
    matched_text: str

class QueryResponse(BaseModel):
    query: str
    answer: str
    citations: List[CitationInfo]
    status: str

# ==========================================
# Router Endpoints
# ==========================================
@router.get("/health")
async def gateway_health():
    return {"status": "ok", "service": "backend-orchestrator-gateway"}

@router.post("/copilot/query", response_model=QueryResponse)
async def route_text_query(payload: QueryRequest):
    print(f"[Gateway] Forwarding query to Core AI: '{payload.query}'")
    try:
        # Forward the text search query to the KMS Core AI microservice
        response = requests.post(CORE_AI_URL, json={"query": payload.query}, timeout=10)
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"Core AI returned an error: {response.text}"
            )
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[Gateway] Request failed connecting to Core AI: {e}")
        raise HTTPException(
            status_code=503, 
            detail="KMS Core AI service is currently unreachable."
        )

@router.post("/copilot/voice-query", response_model=QueryResponse)
async def route_voice_query(file: UploadFile = File(...)):
    print(f"[Gateway] Received voice file: name={file.filename}")
    
    # 1. Save file locally for processing
    temp_file = f"temp_{file.filename}"
    try:
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Call STT (Transcribe Audio)
        # In a real system: transcript = call_whisper_service(temp_file)
        transcript = "Làm cách nào để bật hệ thống điều hòa HVAC trên buồng lái?"
        print(f"[Gateway] Audio transcribed to text: '{transcript}'")

        # 3. Call Core AI Search API
        response = requests.post(CORE_AI_URL, json={"query": transcript}, timeout=10)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Core AI failed executing search.")
            
        result = response.json()
        
        # 4. Call TTS (optional generation of speech response file)
        # call_tts_service(result["answer"])
        
        return result
    except Exception as e:
        print(f"[Gateway] Voice processing failed: {e}")
        raise HTTPException(status_code=500, detail="Voice routing pipeline failed.")
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

@router.post("/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    # Mock Speech-to-Text translation service
    return {"transcript": "Làm thế nào kích hoạt phanh khẩn cấp ADAS?"}

@router.post("/voice/synthesize")
async def synthesize_speech(text: str):
    # Mock Text-to-Speech synthesis service
    return {"audio_url": "/static/audio/response_123.mp3"}
