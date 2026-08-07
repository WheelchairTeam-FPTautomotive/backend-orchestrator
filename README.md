# KMS AI Agent — Backend Orchestrator (Repo 2)

This is the central orchestrator gateway for the **Traceable Voice Copilot** project. It serves as the middleware API connecting the **Cockpit UI (AAOS App)** to the speech services (STT/TTS) and the **KMS Core AI Engine**.

## Table of Contents

- [Technical Stack](#technical-stack)
- [Inbound/Outbound Routing](#inboundoutbound-routing)
- [Folder Structure](#folder-structure)
- [Quick Start (Docker Compose)](#quick-start-docker-compose)
  - [1. Configure the environment](#1-configure-the-environment)
  - [2. Build and start the stack](#2-build-and-start-the-stack)
  - [3. View logs](#3-view-logs)
  - [4. Stop and clean up](#4-stop-and-clean-up)
- [Local Development (without Docker)](#local-development-without-docker)
- [Container Security & Architecture](#container-security--architecture)
- [Health Checks & Startup Ordering](#health-checks--startup-ordering)
- [Voice Pipeline Architecture](#voice-pipeline-architecture)
  - [Query cache & latency headers (#16)](#query-cache--latency-headers-16)
- [Verification & Testing Commands](#verification--testing-commands)
- [API Endpoints](#api-endpoints)
- [VHAL Mock Sender](#vhal-mock-sender)
- [License](#license)

---

## Technical Stack

* **Language**: Python 3.12
* **Package Manager**: `uv`
* **Framework**: FastAPI (using WebSockets for real-time streaming and REST for queries)
* **Ports**: Serves on port `8000`
* **Container Runtime**: Docker + Docker Compose

---

## Inbound/Outbound Routing

```
  [ AAOS Cockpit Client ]
        │ (HTTP / WebSockets on port 8000)
        ▼
  [ Backend Orchestrator ]
        ├──► [ STT Service: Whisper ] (Audio -> Transcript)
        ├──► [ TTS Service: Piper ] (Text -> Voice Audio)
        └──► [ KMS Core AI: RAG Engine ] (Query -> Citations on port 8001)
```

---

## Folder Structure

```
backend-orchestrator/
├── src/
│   ├── main.py            # API Gateway entrypoint
│   └── api/
│       └── v1/
│           └── gateway.py # Transcribe, Synthesize & Search routing
├── scripts/
│   ├── entrypoint.sh      # Privilege-dropping container entrypoint
│   └── vhal_mock_sender.py # Mock VHAL signal emitter
├── pyproject.toml         # Dependency Definitions
├── docker-compose.yml     # Multi-container orchestration
├── Dockerfile             # Multi-stage production image
└── README.md              # This file
```

---

## Quick Start (Docker Compose)

The easiest way to run the full stack is via Docker Compose. This starts both the backend orchestrator and the adjacent `kms-core-ai` service on a shared bridge network.

### 1. Configure the environment

```bash
cp .env.example .env
# Edit .env and fill in your OpenAI API key and any other required values.
```

### 2. Build and start the stack

```bash
# Build images from scratch
docker compose build --no-cache

# Start services in the background
docker compose up -d
```

### 3. View logs

```bash
# Follow all service logs
docker compose logs -f

# Follow only the orchestrator
docker compose logs -f backend-orchestrator

# Follow only the AI core
docker compose logs -f kms-core-ai
```

### 4. Stop and clean up

```bash
# Stop and remove containers, networks, and named volumes
docker compose down -v
```

Once the stack is healthy, the gateway is available at `http://localhost:8000` and the core AI engine at `http://localhost:8001`.

**Interactive API docs (Swagger / OpenAPI):** [http://localhost:8000/docs](http://localhost:8000/docs) · ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Local Development (without Docker)

### 1. Setup Environment

```bash
# In this folder
uv sync
```

### 2. Run the Gateway Server

```bash
uv run uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

---

## Container Security & Architecture

### Non-root runtime

The production image creates and runs as an unprivileged user:

* **Username**: `appuser`
* **UID**: `1000`
* **GID**: `1000`

This limits the blast radius if the gateway process is compromised.

### `gosu` entrypoint for bind-mount permissions

Host bind-mounts (such as `./logs:/app/logs`) are often owned by a different UID/GID than the container's `appuser`. The container starts briefly as `root` through [`scripts/entrypoint.sh`](scripts/entrypoint.sh), which:

1. Runs `chown -R appuser:appuser /app/logs` to fix ownership of the bind-mounted log directory.
2. Uses `gosu` to drop privileges and run the Uvicorn process as `appuser`.

This avoids "Permission denied" errors at runtime while still ensuring the long-running application process is non-root.

```dockerfile
# The Dockerfile sets this entrypoint
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Health Checks & Startup Ordering

### Health probes

Both services expose a health endpoint that Docker probes every 30 seconds:


| Service                | Port   | Health endpoint      |
| ------------------------ | -------- | ---------------------- |
| `backend-orchestrator` | `8000` | `GET /api/v1/health` |
| `kms-core-ai`          | `8001` | `GET /api/v1/health` |

The probe is implemented as a non-privileged inline Python HTTP request:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]
  interval: 30s
  timeout: 5s
  start_period: 10s
  retries: 3
```

### Startup sequencing

The orchestrator depends on the AI core achieving a `healthy` state before it starts:

```yaml
depends_on:
  kms-core-ai:
    condition: service_healthy
```

This ensures that the RAG search endpoint is reachable before the gateway begins accepting requests.

### Restart policy

Both services use `restart: unless-stopped`, so transient failures (e.g., a dependency not yet ready) are automatically retried without manual intervention.

---

## Voice Pipeline Architecture

To fulfill the requirements of reliable, low-latency STT/TTS in both English and Vietnamese (as per Sprint 2 demo requirements), we have elected to use **Groq and Gemini Cloud APIs** over AWS Transcribe/Polly.
* **Why not AWS?** AWS lacks adequate support for Vietnamese conversational speech and TTS naturalness.
* **Why Groq/Gemini?** Groq provides near-instantaneous inference speed, significantly reducing the `stt_ms` latency, while Gemini offers superior Vietnamese speech recognition and synthesis.

**Intent routing (free-talk vs car-control):** see [`docs/intent_routing.md`](docs/intent_routing.md) — ingress normalize, Direct Control via `get_command_id`, Phase 1 classify target **&lt;5ms** (no SageMaker on hot path).

### Query cache & latency headers (#16)

* **Storage:** in-process `cachetools.TTLCache` (`maxsize=1000`, TTL from `QUERY_CACHE_TTL_S`, default **60s**; `0` disables).
* **Key:** `sha256(normalized_query):language:intent` — VI/EN and intent classes never share entries.
* **Payload:** text-query cache stores JSON without `audio_base64` (avoids RAM bloat).
* **Bypass:** request header `X-Cache-Bypass: 1` (or `QUERY_CACHE_TTL_S=0`) for golden/benchmarks.
* **Telemetry:** response headers `X-Cache-Status` (`HIT`|`MISS`|`BYPASS`) and `X-Latency-*-Ms`; JSON body `latency` kept for cockpit developer footer.

```bash
# Second identical VI call should show X-Cache-Status: HIT
curl -i -X POST http://localhost:8000/api/v1/copilot/query \
  -H "Content-Type: application/json" \
  -d '{"query":"Làm sao để kiểm tra phanh?","language":"vi"}'

# Force fresh Core AI (no cache lookup/store)
curl -i -X POST http://localhost:8000/api/v1/copilot/query \
  -H "Content-Type: application/json" \
  -H "X-Cache-Bypass: 1" \
  -d '{"query":"Làm sao để kiểm tra phanh?","language":"vi"}'
```

---

## Verification & Testing Commands

### Check container health status

```bash
docker compose ps
```

Look for `Status: healthy` in the output.

### Verify the process is running as `appuser`

```bash
docker compose exec backend-orchestrator whoami
# Expected: appuser

# Or explicitly as the non-root user
docker compose exec --user appuser backend-orchestrator whoami
```

### Inspect the running process tree

```bash
docker compose top
```

### Test the health endpoint from the host

```bash
curl http://localhost:8000/api/v1/health
# Expected: {"status":"ok","service":"backend-orchestrator-gateway"}

curl http://localhost:8001/api/v1/health
# Expected: {"status":"ready","service":"kms-core-ai"}
```

### Test a text query through the gateway

```bash
curl -X POST http://localhost:8000/api/v1/copilot/query \
  -H "Content-Type: application/json" \
  -d '{"query":"How do I activate the HVAC system?"}'
```

---

## API Endpoints

### 1. `POST /api/v1/copilot/query`

Main query entrypoint. Accepts text + `language` (`vi`|`en`), classifies intent, then RAG / car-control. Short-TTL language-aware cache; see **Query cache & latency headers** above. Explore schemas and try-it-out at `/docs`.

### 2. `POST /api/v1/copilot/voice-query`

Receives uploaded voice audio files, calls the Speech-to-Text service to obtain a transcript, queries the RAG Core AI, and synthesizes the final text response into a playback audio file.

### 3. `POST /api/v1/voice/transcribe`

Utility STT translation endpoint.

### 4. `POST /api/v1/voice/synthesize`

Utility TTS synthesis endpoint.

---

## VHAL Mock Sender

The `scripts/vhal_mock_sender.py` tool generates simulated Vehicle Hardware Abstraction Layer (VHAL) signals for local cockpit integration testing. It broadcasts the same property IDs consumed by the AAOS client:

* `0x11600207` — `PERF_VEHICLE_SPEED` (Float, km/h)
* `0x15200505` — `HVAC_AC_ON` (Boolean)

### Basic usage

```bash
# Run from the backend-orchestrator directory
python scripts/vhal_mock_sender.py --speed-pattern sawtooth --hvac-pattern toggle
```

### Common CLI options


| Option            | Default    | Description                                          |
| ------------------- | ------------ | ------------------------------------------------------ |
| `--interval`      | `1.0`      | Seconds between broadcast ticks                      |
| `--speed-start`   | `60.0`     | Initial speed in km/h                                |
| `--speed-min`     | `0.0`      | Minimum speed in km/h                                |
| `--speed-max`     | `120.0`    | Maximum speed in km/h                                |
| `--speed-step`    | `2.5`      | Speed increment per tick                             |
| `--speed-pattern` | `sawtooth` | `sawtooth`, `ramp`, `random`, or `constant`          |
| `--hvac-start`    | `off`      | Initial HVAC state:`on` or `off`                     |
| `--hvac-pattern`  | `toggle`   | `toggle`, `random`, `constant-on`, or `constant-off` |
| `--duration`      | `0`        | Total seconds to run;`0` = infinite                  |
| `--output-format` | `json`     | `json` (pretty) or `line` (compact)                  |
| `--log-dir`       | `logs`     | Directory for rotating`vhal_mock_sender.log`         |

Every option can also be set via an environment variable with the `VHAL_` prefix, e.g. `VHAL_INTERVAL=2.0` or `LOG_LEVEL=DEBUG`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
