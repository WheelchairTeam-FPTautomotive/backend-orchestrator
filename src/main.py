from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
from api.v1.gateway import router as gateway_router
from core.logging_config import setup_logging

# Configure application logging to stdout for CloudWatch compatibility.
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("API Gateway Orchestrator running with HTTPX Connection Pooling...")
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="KMS Cockpit API Gateway Orchestrator",
    description="Central router orchestrating AAOS inputs, speech processing, and Core RAG lookups.",
    version="1.0.0",
    lifespan=lifespan,
)

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
