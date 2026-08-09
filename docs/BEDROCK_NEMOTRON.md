# A4 — Bedrock model id verification notes (ap-southeast-2)
#
# Locked runtime id: nvidia.nemotron-super-3-120b
# AWS model card: in-region available in ap-southeast-2 (Sydney).
# Geo inference id listed for GovCloud only (us-gov.nvidia.nemotron-super-3-120b) —
# do NOT invent apac.* prefixes without Console confirmation.
#
# Verify in account:
#   aws bedrock list-foundation-models --region ap-southeast-2 \
#     --query "modelSummaries[?contains(modelId, 'nemotron')].modelId"
#   aws bedrock list-inference-profiles --region ap-southeast-2 \
#     --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'nemotron')]"
#
# If Invoke/Converse fails with ResourceNotFoundException or ValidationException,
# replace BEDROCK_MODEL_ID in /etc/kms/core.env with the Console inference profile
# id/ARN for this account, then restart Core.
