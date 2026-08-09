#!/bin/bash
set -euo pipefail
echo "=== ensure core locked env ==="
sudo chown root:ubuntu /etc/kms/*.env
sudo chmod 640 /etc/kms/*.env

# Ensure Bedrock lock keys (idempotent)
sudo python3 - <<'PY'
from pathlib import Path
p = Path("/etc/kms/core.env")
text = p.read_text(encoding="utf-8")
updates = {
    "LLM_PROVIDER": "bedrock",
    "BEDROCK_MODEL_ID": "nvidia.nemotron-super-3-120b",
    "AWS_REGION": "ap-southeast-2",
    "VECTOR_DB_TYPE": "chroma",
    "CHROMA_PATH": "data/chroma_db",
    "CHROMA_COLLECTION": "automotive_manuals",
    "BEDROCK_EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
}
lines = text.splitlines()
keys_seen = set()
out = []
for line in lines:
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k, _, _ = line.partition("=")
    k = k.strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        keys_seen.add(k)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in keys_seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("core.env updated")
PY

# Gateway lock keys
sudo python3 - <<'PY'
from pathlib import Path
p = Path("/etc/kms/gateway.env")
text = p.read_text(encoding="utf-8")
updates = {
    "CORE_AI_URL": "http://127.0.0.1:8001/api/v1/search",
    "VIENEU_TTS_URL": "http://127.0.0.1:8022/v1/audio/speech",
    "AWS_REGION": "ap-southeast-2",
}
lines = text.splitlines()
keys_seen = set()
out = []
for line in lines:
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k, _, _ = line.partition("=")
    k = k.strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        keys_seen.add(k)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in keys_seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("gateway.env updated")
PY

sudo systemctl restart kms-core
sleep 3
sudo systemctl restart kms-gateway

echo "=== wait core ready ==="
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/core_h.json -w "%{http_code}" http://127.0.0.1:8001/api/v1/health || true)
  if [ "$code" = "200" ]; then
    cat /tmp/core_h.json; echo
    break
  fi
  sleep 3
done

echo "=== install awscli v2 if missing ==="
if ! command -v aws >/dev/null 2>&1; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  sudo apt-get update -qq
  sudo apt-get install -y -qq unzip >/dev/null
  unzip -q /tmp/awscliv2.zip -d /tmp
  sudo /tmp/aws/install
fi
aws --version
aws sts get-caller-identity

echo "=== S3 manuals list ==="
BUCKET=backend-orchestrator-dev-manuals-808454010747
aws s3 ls "s3://${BUCKET}/" || true

echo "=== sync local PDFs on box → S3 (source of record) ==="
# Prefer corpus/OEM-looking names; still upload all docs_pdf for backup
aws s3 sync /opt/kms/kms-core-ai/data/docs_pdf "s3://${BUCKET}/docs_pdf/" --exclude ".gitkeep" || true

echo "=== smoke search ==="
python3 - <<'PY'
import json, urllib.request
body = json.dumps({"query": "What is ISOFIX?", "language": "en"}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8001/api/v1/search",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.loads(resp.read().decode())
print("keys", sorted(data.keys())[:20])
ans = data.get("answer") or data.get("response") or data.get("text") or ""
print("answer_preview:", (ans[:400] if isinstance(ans, str) else str(ans)[:400]))
print("handoff", data.get("handoff"))
print("sources", len(data.get("sources") or data.get("citations") or []))
PY

echo "=== gateway copilot text ==="
python3 - <<'PY'
import json, urllib.request
body = json.dumps({"text": "What is ISOFIX?", "language": "en"}).encode()
# try common endpoints
for path in ("/api/v1/copilot/query", "/copilot/query", "/api/v1/query"):
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8000{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
        print("PATH", path, "OK", raw[:500])
        break
    except Exception as e:
        print("PATH", path, "FAIL", e)
PY

echo "=== edge tts via gateway if available ==="
curl -s http://127.0.0.1:8000/api/v1/health
echo
systemctl is-active kms-core kms-gateway
df -h / | tail -1
