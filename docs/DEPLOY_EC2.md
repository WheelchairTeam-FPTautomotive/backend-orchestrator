# One-EC2 deploy runbook (all-in-one)

Locked stack: **Acc → Lat → Budget**. One EC2 · Bedrock Nemotron · Chroma · two env files.  
**Two deploy methods** — pick one (do not mix on the same box without teardown).

| Method | Playbook | Process manager | When to use |
|--------|----------|-----------------|-------------|
| **A — Native (recommended)** | `playbooks/deploy-ec2-native.yml` | systemd + uv `.venv` | Single EC2, Budget, avoids Docker disk |
| **B — Compose** | `playbooks/deploy-ec2-compose.yml` | Docker Compose on EC2 | Parity with local Compose; needs **80GB+** disk |
| **C — ECS (legacy)** | `playbooks/deploy.yml` | Fargate | Managed containers (not this EC2 lock) |

**VieNeu (CPU):** native Method A clones [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), runs `uv sync` (v3 Turbo ONNX, torch-free), serves OpenAI `/v1/audio/speech` on `:8022` via `scripts/vieneu_openai_server.py`. Docker VieNeu is GPU-only — not used here.

Related: [BEDROCK_NEMOTRON.md](BEDROCK_NEMOTRON.md) · env samples in [env-samples/](env-samples/)

---

## 1. Architecture (one box, two env files)

```text
Cockpit ──► EC2 :8000  gateway   (/etc/kms/gateway.env)
              └──────► :8001  Core AI  (/etc/kms/core.env) ──► Bedrock Nemotron
S3 manuals ──ingest──► on-box Chroma
```

| Service | Port | Env file | Method A | Method B |
|---------|------|----------|----------|----------|
| Gateway | 8000 | `/etc/kms/gateway.env` | `kms-gateway.service` | Compose service |
| Core AI | 8001 | `/etc/kms/core.env` | `kms-core.service` | Compose service |
| VieNeu | 8022 | — | optional `vieneu.service` | same |

STM: gateway **`--workers 1`**. Keep **two** env files.

---

## 2. Order of operations

```text
0. AWS API login + EC2 SSH key pair
1. Terraform apply → EC2 + EIP + manuals S3
2. Choose Method A or B → Ansible playbook
3. Edit /etc/kms/*.env secrets
4. Ingest PDFs → Chroma
5. Smoke health
```

---

## 2b. Credentials — do not confuse these two


| Thing                                   | What it is                  | Where it goes                                                                 |
| --------------------------------------- | --------------------------- | ----------------------------------------------------------------------------- |
| **Access key + secret + session token** | Temporary AWS **API** login | PowerShell env / `aws login` — **never** `ec2_key_name`                       |
| **EC2 key pair (`.pem`)**               | SSH into the instance       | `ec2_key_name` in `terraform.tfvars` + Ansible `ansible_ssh_private_key_file` |


### A) AWS API login (so `terraform plan` works)

If you see `No valid credential sources` or `credentials are still expired`:

```powershell
aws login
aws sts get-caller-identity
```

After a successful login, export short-lived keys into **this shell** (Terraform reads these env vars):

```powershell
aws configure export-credentials --format env
# Then copy/paste the printed lines, or on PowerShell evaluate them:
aws configure export-credentials --format env | ForEach-Object {
  if ($_ -match '^export ([^=]+)="(.*)"$') {
    Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
  }
}
# Bash/WSL:
# eval "$(aws configure export-credentials --format env)"

$env:AWS_DEFAULT_REGION = "ap-southeast-2"
aws sts get-caller-identity
```

Or paste console “Command line or programmatic access” into the **same shell**:

```powershell
$env:AWS_ACCESS_KEY_ID     = "ASIA..."
$env:AWS_SECRET_ACCESS_KEY = "..."
$env:AWS_SESSION_TOKEN      = "..."
$env:AWS_DEFAULT_REGION     = "ap-southeast-2"
aws sts get-caller-identity
```

Do **not** put Access Key ID into `ec2_key_name`. Re-run `aws login` + `export-credentials` when the session expires.

### B) EC2 key pair (SSH) — create before apply

**Console:** EC2 → region **Sydney (ap-southeast-2)** → **Key Pairs** → **Create key pair**  

- Name e.g. `kms-ec2` · Type **RSA** · Format `**.pem`**  
- Download the `.pem` once and keep it safe

**CLI:**

```powershell
aws ec2 create-key-pair `
  --region ap-southeast-2 `
  --key-name kms-ec2 `
  --key-type rsa `
  --key-format pem `
  --query "KeyMaterial" `
  --output text | Out-File -Encoding ascii $env:USERPROFILE\.ssh\kms-ec2.pem
```

Then in `terraform.tfvars`:

```hcl
ec2_key_name     = "kms-ec2"           # exact Key Pairs name in Sydney
ssh_ingress_cidr = "YOUR.PUBLIC.IP/32" # your laptop public IP
```

Ansible later:

```yaml
# ansible/inventory/ec2.yml
ansible_ssh_private_key_file: C:/Users/YOU/.ssh/kms-ec2.pem
```

---

## 3. Terraform (create the box)

```bash
cd backend-orchestrator/terraform
cp terraform.tfvars.example terraform.tfvars
# REQUIRED: set ec2_key_name + ssh_ingress_cidr (see §2b)
# Keep: enable_ecs=false, enable_aoss=false, deploy_sagemaker_model=false
aws sts get-caller-identity   # must succeed first
terraform plan
terraform apply
```

Note outputs:

- `ec2_public_ip`
- `manuals_bucket_name`
- `ec2_instance_id`

If hackathon blocks `iam:CreateRole`:

```hcl
create_ec2_instance_profile        = false
existing_ec2_instance_profile_name = "YourProfile"
```

---

## 4. Deploy methods (Ansible)

WSL: `export ANSIBLE_ROLES_PATH="$(pwd)/roles"` from `backend-orchestrator/ansible`.  
If Gathering Facts hangs: add `-e gather_facts=false`.

### Method A — Native systemd (recommended)

```bash
# Optional: clear failed Compose leftovers first
ssh -i ~/.ssh/kms-ec2.pem ubuntu@YOUR_EIP '
  cd /opt/kms/backend-orchestrator && sudo docker compose down 2>/dev/null || true
  sudo docker system prune -af 2>/dev/null || true
'

cd /mnt/h/Project/KMS/backend-orchestrator/ansible
export ANSIBLE_ROLES_PATH="$(pwd)/roles"
ansible-playbook -i inventory/ec2.yml playbooks/deploy-ec2-native.yml \
  -e gather_facts=false
```

Verify:

```bash
ssh -i ~/.ssh/kms-ec2.pem ubuntu@YOUR_EIP \
  'sudo systemctl status kms-core kms-gateway --no-pager; curl -s localhost:8001/api/v1/health'
```

### Method B — Docker Compose on EC2

Needs **80GB+** root disk (builds fill 40GB). For managed containers long-term, use **Method C (ECS)** instead.

```bash
cd /mnt/h/Project/KMS/backend-orchestrator/ansible
export ANSIBLE_ROLES_PATH="$(pwd)/roles"
ansible-playbook -i inventory/ec2.yml playbooks/deploy-ec2-compose.yml \
  -e gather_facts=false
```

Verify: `docker compose -f /opt/kms/backend-orchestrator/docker-compose.yml ps`

### Method C — ECS Fargate (legacy)

```bash
ansible-playbook -i inventory/localhost.yml playbooks/deploy.yml
```

Requires Terraform `enable_ecs=true` (off by default for Budget).

### Switching A ↔ B

Do not run both at once. Tear down the other first (Compose down **or** `systemctl stop kms-gateway kms-core`).

---

## 5. Env files — what you type on AWS

Samples (repo):

- [env-samples/prod.gateway.env.sample](env-samples/prod.gateway.env.sample)
- [env-samples/prod.core.env.sample](env-samples/prod.core.env.sample)

On the instance after Ansible:

```bash
sudo nano /etc/kms/gateway.env
sudo nano /etc/kms/core.env
```

### Gateway (`gateway.env`) — fill


| Var              | Value                                   |
| ---------------- | --------------------------------------- |
| `CORE_AI_URL`    | `http://127.0.0.1:8001/api/v1/search`   |
| `VIENEU_TTS_URL` | `http://127.0.0.1:8022/v1/audio/speech` |
| `GROQ_API_KEY`   | your Groq key (STT)                     |
| `AWS_REGION`     | `ap-southeast-2`                        |


### Core (`core.env`) — fill / confirm


| Var                          | Value                                     |
| ---------------------------- | ----------------------------------------- |
| `VECTOR_DB_TYPE`             | `chroma`                                  |
| `LLM_PROVIDER`               | `bedrock`                                 |
| `BEDROCK_MODEL_ID`           | `nvidia.nemotron-super-3-120b`            |
| `AWS_REGION`                 | `ap-southeast-2`                          |
| `AWS_ACCESS_KEY_ID` / secret | **leave empty** if instance profile works |


Then restart:

```bash
sudo systemctl restart kms-core kms-gateway
sudo systemctl status kms-core kms-gateway --no-pager
```

**Do not commit** real `.env` files. Local laptop `.env` is separate from `/etc/kms/`*.

---

## 6. Bedrock model id

Default: `nvidia.nemotron-super-3-120b` in `ap-southeast-2`.

If invoke fails (`ResourceNotFoundException` / `ValidationException`), use the Console **inference profile** id/ARN — see [BEDROCK_NEMOTRON.md](BEDROCK_NEMOTRON.md). Do not invent `apac.` prefixes.

---

## 7. PDFs → Chroma

1. Upload manuals to `manuals_bucket_name` (Terraform output).
2. On EC2, sync/download into Core’s `DOCS_PDF_DIR` / corpus path.
3. Run Core ingest (project ingest script / documented CLI in `kms-core-ai`).
4. Confirm `VECTOR_DB_TYPE=chroma` and collection `automotive_manuals`.

---

## 8. Smoke

```bash
# From laptop
cd backend-orchestrator
./scripts/smoke_ec2_stack.ps1 -BaseUrl http://EC2_PUBLIC_IP
# or
./scripts/smoke_ec2_stack.sh http://EC2_PUBLIC_IP
```

Expect: gateway `:8000/api/v1/health`, Core `:8001/api/v1/health`, VieNeu `:8022` open.

Optional: re-run diverse Acc with Core on Bedrock Nemotron.

### Carsky IVI → this EC2 (do not use EIP in the app)

Trout/Carsky guests **cannot egress** to `http://<EIP>:8000/`. Use the laptop as a bridge:

```powershell
# After Reach ADB is up (localhost:5555):
powershell.exe -ExecutionPolicy Bypass -File `
  "H:\Project\KMS\KMS-AI-Agent-for-Automotive-Documentation\carsky-backend-tunnel.ps1" `
  -Backend Ec2 -Ec2Host <EIP>
```

That script: `ssh -L 127.0.0.1:8000:127.0.0.1:8000` + `adb reverse tcp:8000` + health from laptop **and** device.

In cockpit Dev Settings set Backend URL to **`http://127.0.0.1:8000/`** only.

Full Carsky runbook: `KMS-AI-Agent-for-Automotive-Documentation/README-carsky.md`.

TTS: Edge is **in-process** on `kms-gateway` (Microsoft); VieNeu is `vieneu.service` `:8022`. Cockpit plays MP3 via `MediaPlayer` — if gateway logs `[Edge TTS] Generated` but cabin is silent, enable Carsky **Audio/speaker** (HAL may show `audio_vbuffer is full` when the browser is not draining).

---

## 9. Local Compose (dev laptop)

Not the same as **Method B** (Compose *on* EC2). Local:

```bash
cd backend-orchestrator
cp .env.example .env
cp ../kms-core-ai/.env.example ../kms-core-ai/.env
# Acc freeze without Bedrock: set LLM_PROVIDER=ollama in kms-core-ai/.env
docker compose up --build
```

Two env files. VieNeu is host-side until wired into Compose.

---

## 10. Rejects

- Running Method A and B on the same box at once
- Merging gateway + Core into one env file
- AOSS as v1 RAG / ECS as default v1 Budget path
- Empty `VIENEU_TTS_URL` in prod
- Gateway workers > 1
- Committing secrets into git

