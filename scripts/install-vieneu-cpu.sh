#!/bin/bash
# Install VieNeu-TTS v3 Turbo CPU (ONNX) + OpenAI server on :8022
set -euo pipefail
export PATH="/usr/local/bin:$PATH"
export UV_PYTHON_INSTALL_DIR=/opt/kms/.uv-python
export HF_HOME=/opt/kms/vieneu/.cache/huggingface
export HOME=/opt/kms/vieneu

sudo mkdir -p /opt/kms/vieneu/.cache/huggingface /opt/kms/VieNeu-TTS
sudo chown -R ubuntu:ubuntu /opt/kms/vieneu /opt/kms/VieNeu-TTS

if [ ! -d /opt/kms/VieNeu-TTS/.git ]; then
  git clone --depth 1 https://github.com/pnnbao97/VieNeu-TTS.git /opt/kms/VieNeu-TTS
else
  git -C /opt/kms/VieNeu-TTS fetch --depth 1 origin main
  git -C /opt/kms/VieNeu-TTS reset --hard origin/main
fi

cd /opt/kms/VieNeu-TTS
echo "=== uv sync (CPU ONNX) ==="
uv sync
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]"

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg >/dev/null || true

echo "=== warm model ==="
.venv/bin/python - <<'PY'
from vieneu import Vieneu
e = Vieneu(backend="onnx")
print("voices", e.list_preset_voices())
a = e.infer("Xin chào từ KMS.", voice="Trúc Ly")
print("warmup_samples", len(a))
PY

echo "=== install systemd unit ==="
# openai_server.py must already be copied to /opt/kms/vieneu/
test -f /opt/kms/vieneu/openai_server.py

sudo tee /etc/systemd/system/vieneu.service >/dev/null <<'UNIT'
[Unit]
Description=KMS VieNeu TTS v3 Turbo (CPU ONNX OpenAI server)
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/kms/VieNeu-TTS
Environment=HOME=/opt/kms/vieneu
Environment=HF_HOME=/opt/kms/vieneu/.cache/huggingface
Environment=PATH=/opt/kms/VieNeu-TTS/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/kms/VieNeu-TTS/.venv/bin/python /opt/kms/vieneu/openai_server.py --host 127.0.0.1 --port 8022
Restart=on-failure
RestartSec=8
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now vieneu.service

# gateway env
sudo sed -i 's|^VIENEU_TTS_URL=.*|VIENEU_TTS_URL=http://127.0.0.1:8022/v1/audio/speech|' /etc/kms/gateway.env
grep -q '^VIENEU_VOICE=' /etc/kms/gateway.env && sudo sed -i 's|^VIENEU_VOICE=.*|VIENEU_VOICE=truc_ly|' /etc/kms/gateway.env || echo 'VIENEU_VOICE=truc_ly' | sudo tee -a /etc/kms/gateway.env >/dev/null
sudo systemctl restart kms-gateway

echo "=== wait health ==="
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8022/health >/tmp/vieneu_h.json 2>/dev/null; then
    cat /tmp/vieneu_h.json; echo
    break
  fi
  sleep 3
done

echo "=== speech smoke ==="
curl -fsS -X POST http://127.0.0.1:8022/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"vieneu","input":"Xin chào","voice":"truc_ly","response_format":"wav"}' \
  -o /tmp/vieneu_smoke.wav
ls -la /tmp/vieneu_smoke.wav
systemctl is-active vieneu kms-gateway
df -h / | tail -1
