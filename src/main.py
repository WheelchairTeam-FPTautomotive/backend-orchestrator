from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.v1.gateway import router as gateway_router

app = FastAPI(
    title="KMS Cockpit API Gateway Orchestrator",
    description="Central router orchestrating AAOS inputs, speech processing, and Core RAG lookups.",
    version="1.0.0"
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
    print("API Gateway Orchestrator running on port 8000...")
