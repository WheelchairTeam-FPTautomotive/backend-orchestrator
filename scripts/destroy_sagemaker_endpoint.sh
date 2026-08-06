#!/usr/bin/env bash
# Destroy / teardown SageMaker endpoint via Ansible (keeps S3 artifacts).
# Dry-run printable when AWS profile / credentials are missing.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANSIBLE_CMD="$(command -v ansible-playbook || echo ansible-playbook)"
AWS_CLI="$(command -v aws || command -v aws.exe || echo aws)"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]] || [[ -z "${AWS_PROFILE:-}${AWS_ACCESS_KEY_ID:-}" ]]; then
  if [[ "${1:-}" == "--dry-run" ]] || ! $AWS_CLI sts get-caller-identity &>/dev/null; then
    DRY_RUN=1
  fi
fi

if [[ $DRY_RUN -eq 1 ]]; then
  cat <<'EOF'
[destroy_sagemaker_endpoint] DRY-RUN — no AWS calls.

When mentor IAM is approved, run:
  cd ansible
  ansible-playbook -i inventory/localhost.yml playbooks/teardown-models.yml

Then verify:
  aws sagemaker list-endpoints --region ap-southeast-2 \
    --query "Endpoints[?EndpointStatus=='InService'].EndpointName"

Expect: no GPU InService endpoints left overnight.
Log date/who/apply-minutes/destroy proof in docs/sagemaker_gpu_runbook.md on-hours table.
EOF
  exit 0
fi

echo "==> Running teardown-models.yml"
(
  cd "$ROOT/ansible"
  $ANSIBLE_CMD -i inventory/localhost.yml playbooks/teardown-models.yml
)

echo "==> Listing InService endpoints"
$AWS_CLI sagemaker list-endpoints --region "${AWS_DEFAULT_REGION:-ap-southeast-2}" \
  --query "Endpoints[?EndpointStatus=='InService'].[EndpointName,EndpointStatus]" \
  --output table || true

echo "Done. Confirm Cost Explorer shows endpoint stopped."
