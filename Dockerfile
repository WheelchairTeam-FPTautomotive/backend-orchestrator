# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for KMS Backend Orchestrator (FastAPI gateway).
# Follows hackathon starter-kit conventions: python 3.12, uv package manager,
# multi-stage build, and a non-root runtime user.

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Install uv for fast, reproducible Python dependency management.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /build

# Copy dependency definitions first to maximise Docker layer caching.
COPY pyproject.toml ./

# Create a virtual environment and install production dependencies.
# --no-install-project avoids copying the full source before resolving deps.
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -r pyproject.toml

# ------------------------------------------------------------------------------
# Stage 2: Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Create a non-root user for production runtime security.
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy the prepared virtual environment from the builder stage.
COPY --from=builder /build/.venv /app/.venv

# Make the virtual environment binaries available on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy application source code and helper scripts.
COPY src/ ./src/
COPY scripts/ ./scripts/

# Ensure the entrypoint script is executable.
RUN chmod +x /app/scripts/entrypoint.sh

# Run as the non-root user. All application logs are emitted to stdout so no
# local log directory or runtime permission fixes are required.
USER appuser

# Expose the gateway port.
EXPOSE 8000

# Health check aligned with the starter-kit pattern (30s interval).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Use the entrypoint to run the application.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Run the FastAPI gateway via the Python module runner to avoid the shebang
# mismatch between multi-stage build layers when calling the .venv binary.
CMD ["python", "-m", "uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
