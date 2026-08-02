#!/usr/bin/env bash
# Local validation script for the backend-orchestrator deployment pipeline.
# Runs the same checks as the GitHub Actions CI workflow.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_CMD="$(command -v terraform || command -v terraform.exe || echo terraform)"
ANSIBLE_CMD="$(command -v ansible-playbook || echo ansible-playbook)"

echo "==> Running Terraform format check"
(cd "$ROOT/terraform" && $TERRAFORM_CMD fmt -check -diff)

echo "==> Running Terraform init"
(cd "$ROOT/terraform" && $TERRAFORM_CMD init -backend=false)

echo "==> Running Terraform validate"
(cd "$ROOT/terraform" && $TERRAFORM_CMD validate)

echo "==> Running Ansible syntax check"
(
  cd "$ROOT/ansible"
  $ANSIBLE_CMD -i inventory/localhost.yml playbooks/deploy.yml --syntax-check
)

echo "==> All validation checks passed"
