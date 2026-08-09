#!/bin/bash
set -euo pipefail
export PATH="/usr/local/bin:$PATH"
export UV_PYTHON_INSTALL_DIR=/opt/kms/.uv-python

sudo systemctl stop kms-core kms-gateway || true
sudo chown -R ubuntu:ubuntu /opt/kms
sudo chown root:ubuntu /etc/kms/*.env 2>/dev/null || true
sudo chmod 640 /etc/kms/*.env 2>/dev/null || true
mkdir -p /opt/kms/.uv-python
find /opt/kms -type d -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true

uv python install 3.12

cd /opt/kms/backend-orchestrator
rm -rf .venv
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
echo "GATEWAY_OK $(readlink -f .venv/bin/python)"

cd /opt/kms/kms-core-ai
rm -rf .venv
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
echo "CORE_OK $(readlink -f .venv/bin/python)"

sudo systemctl daemon-reload
sudo systemctl restart kms-core
sleep 5
sudo systemctl restart kms-gateway
sleep 8
systemctl is-active kms-core || true
systemctl is-active kms-gateway || true
curl -s -o /dev/null -w "core:%{http_code}\n" http://127.0.0.1:8001/api/v1/health || true
curl -s -o /dev/null -w "gw:%{http_code}\n" http://127.0.0.1:8000/api/v1/health || true
sudo journalctl -u kms-core -n 50 --no-pager
