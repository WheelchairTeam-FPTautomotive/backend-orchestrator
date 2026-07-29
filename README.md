# KMS AI Agent — Backend Orchestrator (Repo 2)

This is the central orchestrator gateway for the **Traceable Voice Copilot** project. It serves as the middleware API connecting the **Cockpit UI (AAOS App)** to the speech services (STT/TTS) and the **KMS Core AI Engine**.

---

## Technical Stack
* **Language**: Python 3.12
* **Package Manager**: `uv`
* **Framework**: FastAPI (using WebSockets for real-time streaming and REST for queries)
* **Ports**: Serves on port `8000`

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
│   └── vhal_mock_sender.py # Mock VHAL signal emitter
├── pyproject.toml         # Dependency Definitions
└── README.md              # This file
```

---

## Getting Started

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

## API Endpoints

### 1. `POST /api/v1/copilot/query`
Main query entrypoint. Accepts text, forwards the request to the RAG Core AI (`http://localhost:8001/api/v1/search`), and returns the grounded answer and source citation array.

### 2. `POST /api/v1/copilot/voice-query`
Receives uploaded voice audio files, calls the Speech-to-Text service to obtain a transcript, queries the RAG Core AI, and synthesizes the final text response into a playback audio file.

### 3. `POST /api/v1/voice/transcribe`
Utility STT translation endpoint.

### 4. `POST /api/v1/voice/synthesize`
Utility TTS synthesis endpoint.

---

## VHAL Mock Sender

The `scripts/vhal_mock_sender.py` tool generates simulated Vehicle Hardware Abstraction Layer (VHAL) signals for local cockpit integration testing. It broadcasts the same property IDs consumed by the AAOS client:

- `0x11600207` — `PERF_VEHICLE_SPEED` (Float, km/h)
- `0x15200505` — `HVAC_AC_ON` (Boolean)

### Basic usage

```bash
# Run from the backend-orchestrator directory
python scripts/vhal_mock_sender.py --speed-pattern sawtooth --hvac-pattern toggle
```

### Common CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--interval` | `1.0` | Seconds between broadcast ticks |
| `--speed-start` | `60.0` | Initial speed in km/h |
| `--speed-min` | `0.0` | Minimum speed in km/h |
| `--speed-max` | `120.0` | Maximum speed in km/h |
| `--speed-step` | `2.5` | Speed increment per tick |
| `--speed-pattern` | `sawtooth` | `sawtooth`, `ramp`, `random`, or `constant` |
| `--hvac-start` | `off` | Initial HVAC state: `on` or `off` |
| `--hvac-pattern` | `toggle` | `toggle`, `random`, `constant-on`, or `constant-off` |
| `--duration` | `0` | Total seconds to run; `0` = infinite |
| `--output-format` | `json` | `json` (pretty) or `line` (compact) |
| `--log-dir` | `logs` | Directory for rotating `vhal_mock_sender.log` |

Every option can also be set via an environment variable with the `VHAL_` prefix, e.g. `VHAL_INTERVAL=2.0` or `LOG_LEVEL=DEBUG`.
