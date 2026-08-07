from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
import os
from api.v1.gateway import router as gateway_router
from core.logging_config import setup_logging

# Configure application logging to stdout for CloudWatch compatibility.
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("API Gateway Orchestrator running with HTTPX Connection Pooling...")
    timeout_s = float(os.getenv("CORE_AI_TIMEOUT_S", "120"))
    app.state.http_client = httpx.AsyncClient(timeout=timeout_s)
    yield
    await app.state.http_client.aclose()


# --- START MODIFICATION ---
# OpenAPI tag groups for Swagger UI (/docs) — issue #16
OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness probes for Docker / compose startup ordering.",
    },
    {
        "name": "copilot",
        "description": (
            "Typed cockpit queries. Language-aware short-TTL cache "
            "(`QUERY_CACHE_TTL_S`, default 60s). Request `X-Cache-Bypass: 1` for golden eval. "
            "Response headers: `X-Cache-Status`, `X-Latency-*-Ms`. JSON `latency` for cockpit footer."
        ),
    },
    {
        "name": "voice",
        "description": "STT / TTS / voice-query upload pipeline.",
    },
]

app = FastAPI(
    title="KMS Cockpit API Gateway Orchestrator",
    description=(
        "Central router orchestrating AAOS inputs, speech processing, and Core RAG lookups. "
        "Interactive OpenAPI: `/docs` (Swagger UI), `/redoc`."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)
# --- END MODIFICATION ---

# CORS middleware for client connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register gateway routes
app.include_router(gateway_router)


@app.on_event("startup")
async def startup_event():
    logger.info("API Gateway Orchestrator running on port 8000...")
