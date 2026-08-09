#!/usr/bin/env bash
# Smoke checks for locked one-EC2 stack (A5).
# Usage: ./scripts/smoke_ec2_stack.sh [http://HOST]
set -euo pipefail
BASE="${1:-http://127.0.0.1}"
BASE="${BASE%/}"

echo "== Gateway health =="
curl -fsS "$BASE:8000/api/v1/health" | head -c 500
echo

echo "== Core health =="
curl -fsS "$BASE:8001/api/v1/health" | head -c 500
echo

echo "== VieNeu port =="
if command -v nc >/dev/null 2>&1; then
  nc -z -w 3 "${BASE#http://}" 8022 && echo "8022 open" || echo "8022 CLOSED (start vieneu.service)"
else
  curl -fsS -o /dev/null -w "%{http_code}\n" --connect-timeout 3 "http://${BASE#http://}:8022/" || echo "VieNeu probe soft-fail"
fi

echo "== Terraform gate defaults (local) =="
if command -v terraform >/dev/null 2>&1; then
  (
    cd "$(dirname "$0")/../terraform"
    terraform validate
    echo "enable_ecs/aoss should be false in tfvars for Budget lock"
  )
fi

echo "Smoke complete."
