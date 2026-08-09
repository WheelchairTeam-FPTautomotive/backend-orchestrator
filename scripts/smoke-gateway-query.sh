#!/bin/bash
set -euo pipefail
python3 <<'PY'
import json, urllib.request

def post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.status, json.loads(resp.read().decode())

# Gateway QueryRequest typically uses "query" not "text"
for body in (
    {"query": "What is ISOFIX?", "language": "en"},
    {"text": "What is ISOFIX?", "language": "en"},
    {"message": "What is ISOFIX?", "language": "en"},
):
    try:
        status, data = post("http://127.0.0.1:8000/api/v1/copilot/query", body)
        print("OK body keys", list(body.keys()), "status", status)
        print("response keys", list(data.keys())[:15])
        ans = data.get("answer") or data.get("response") or ""
        print("answer_preview", str(ans)[:300])
        print("audio", "audio_base64" in data, "len", len(data.get("audio_base64") or "") if data.get("audio_base64") else 0)
        break
    except Exception as e:
        print("FAIL", list(body.keys()), e)

# TTS endpoint
try:
    status, data = post("http://127.0.0.1:8000/api/v1/copilot/tts", {"text": "Xin chao", "language": "vi"})
    print("TTS status", status, "keys", list(data.keys())[:10])
    print("audio_len", len(data.get("audio_base64") or data.get("audio") or "") if isinstance(data, dict) else None)
except Exception as e:
    print("TTS FAIL", e)
PY
