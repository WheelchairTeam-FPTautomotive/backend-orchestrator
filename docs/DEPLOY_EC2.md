# Deploy on one EC2 (locked Acc → Lat → Budget)

Single host runs gateway, Core AI (Chroma), and VieNeu. PDFs live in S3 and are ingested into on-box Chroma. Answer LLM is Bedrock Nemotron; Ollama Qwen is Budget fallback only.

## Ports

| Service | Port | Process manager |
|---------|------|-----------------|
| Gateway | 8000 | systemd `kms-gateway.service` or Docker Compose |
| Core AI | 8001 | systemd `kms-core.service` or Docker Compose |
| VieNeu TTS | 8022 | **systemd `vieneu.service`** (required) |

STM requires **Uvicorn `--workers 1`** on the gateway. Do not scale workers.

## Env files

```bash
# On the box (Ansible drops these from deploy/env samples):
/etc/kms/gateway.env   # from docs/env-samples/prod.gateway.env.sample
/etc/kms/core.env      # from docs/env-samples/prod.core.env.sample
```

Critical vars:

```env
# gateway
CORE_AI_URL=http://127.0.0.1:8001/api/v1/search
VIENEU_TTS_URL=http://127.0.0.1:8022/v1/audio/speech

# core
VECTOR_DB_TYPE=chroma
LLM_PROVIDER=bedrock
BEDROCK_MODEL_ID=nvidia.nemotron-super-3-120b
AWS_REGION=ap-southeast-2
```

If Bedrock returns `ResourceNotFoundException` / `ValidationException`, open the Bedrock console in Sydney and replace `BEDROCK_MODEL_ID` with the account’s **inference profile** id/ARN. Do not invent `apac.` prefixes.

## Ansible (preferred)

```bash
cd backend-orchestrator/ansible
# Edit inventory/ec2.yml with host IP + SSH user/key
ansible-playbook -i inventory/ec2.yml playbooks/deploy-ec2-stack.yml
```

Role `ec2_kms_stack` installs packages, env files, Compose or systemd units, and enables `vieneu.service`.

## Local Compose (dev)

```bash
cd backend-orchestrator
cp .env.example .env
cp ../kms-core-ai/.env.example ../kms-core-ai/.env
# For local Acc freeze without Bedrock, set Core LLM_PROVIDER=ollama in kms-core-ai/.env
docker compose up --build
```

VieNeu is not a Compose service — run it on the host or skip TTS fallback (Edge-only).

## Terraform (lean defaults)

```bash
cd backend-orchestrator/terraform
cp terraform.tfvars.example terraform.tfvars
# enable_ecs = false, enable_aoss = false (defaults)
terraform plan
terraform apply
```

Outputs: `ec2_public_ip`, `manuals_bucket_name`, `instance_id`.

Legacy ECS Fargate / AOSS / SageMaker stay behind flags (`enable_ecs`, `enable_aoss`, `deploy_sagemaker_model`). Do not enable for v1 Budget lock.

## Smoke

```bash
# From laptop or on-box:
./scripts/smoke_ec2_stack.sh http://EC2_IP
# or PowerShell:
./scripts/smoke_ec2_stack.ps1 -BaseUrl http://EC2_IP
```

Checks: gateway `/api/v1/health`, Core `/api/v1/health`, VieNeu port 8022, `terraform validate`.

Bedrock id notes: [`BEDROCK_NEMOTRON.md`](BEDROCK_NEMOTRON.md).

## Rejects

- AOSS as default RAG
- ECS Fargate as v1 product path
- Empty `VIENEU_TTS_URL` in prod
- Gateway workers > 1
