#!/usr/bin/env bash
# Permission-safe pseudo checks for SageMaker GPU IaC (issues #12 / #17).
# NEVER runs terraform apply. Plan with mock creds is soft-fail (data sources need STS).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_CMD="$(command -v terraform || command -v terraform.exe || echo terraform)"
ANSIBLE_CMD="$(command -v ansible-playbook || echo ansible-playbook)"

HARD_FAIL=0
PLAN_SOFT_FAIL=0

echo "==> [pseudo] Terraform fmt -check"
# Avoid -diff: Windows hosts often lack GNU `diff` in PATH
if ! (cd "$ROOT/terraform" && $TERRAFORM_CMD fmt -check); then
  HARD_FAIL=1
fi

echo "==> [pseudo] Terraform init -backend=false"
if ! (cd "$ROOT/terraform" && $TERRAFORM_CMD init -backend=false -input=false); then
  HARD_FAIL=1
fi

echo "==> [pseudo] Terraform validate"
if ! (cd "$ROOT/terraform" && $TERRAFORM_CMD validate); then
  HARD_FAIL=1
fi

echo "==> [pseudo] Ansible syntax-check (ECS + SageMaker deploy/teardown)"
(
  cd "$ROOT/ansible"
  $ANSIBLE_CMD -i inventory/localhost.yml playbooks/deploy.yml --syntax-check
  $ANSIBLE_CMD -i inventory/localhost.yml playbooks/deploy-models.yml --syntax-check
  $ANSIBLE_CMD -i inventory/localhost.yml playbooks/teardown-models.yml --syntax-check
) || HARD_FAIL=1

echo "==> [pseudo] Terraform plan (mock AWS creds, soft-fail)"
# data.aws_caller_identity typically fails with fake keys — do not hard-fail CI.
set +e
(
  cd "$ROOT/terraform"
  AWS_ACCESS_KEY_ID=mock_key \
  AWS_SECRET_ACCESS_KEY=mock_secret \
  AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-southeast-2}" \
  AWS_EC2_METADATA_DISABLED=true \
  $TERRAFORM_CMD plan \
    -var="deploy_sagemaker_model=true" \
    -refresh=false \
    -input=false \
    -lock=false
)
PLAN_RC=$?
set -e
if [[ $PLAN_RC -ne 0 ]]; then
  PLAN_SOFT_FAIL=1
  echo "WARN: terraform plan soft-failed (rc=$PLAN_RC). Expected offline without real STS."
  echo "      Hard gates remain: fmt / validate / ansible syntax."
fi

if [[ $HARD_FAIL -ne 0 ]]; then
  echo "FAIL: hard pseudo checks failed"
  exit 1
fi

echo "PASS: hard pseudo checks ok (plan_soft_fail=$PLAN_SOFT_FAIL)"
exit 0
