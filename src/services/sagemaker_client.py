"""SageMaker Runtime client for local LLM inference.

This module is used by intent_router.py as a low-latency replacement for the
serverless Bedrock API. It reads the endpoint configuration from environment
variables injected by Terraform:

  - SAGEMAKER_LLM_ENDPOINT_NAME
  - SAGEMAKER_REGION
  - SAGEMAKER_USE_VPC_ENDPOINT
  - SAGEMAKER_VPC_ENDPOINT_URL
"""

import json
import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


VALID_INTENTS = {"CAR_CONTROL", "RAG_SEARCH", "FREE_TALK"}

# Strict timeouts to keep intent classification under the <200ms AC when warm.
SAGEMAKER_CONFIG = Config(
    connect_timeout=5,
    read_timeout=5,
    retries={"max_attempts": 0},
)


def get_sagemaker_runtime_client() -> boto3.client:
    """Return a sagemaker-runtime boto3 client.

    Uses the VPC endpoint URL when SAGEMAKER_USE_VPC_ENDPOINT is true so that
    ECS tasks in private subnets can reach the endpoint without public internet.
    """
    region = os.getenv("SAGEMAKER_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2"))
    use_vpc_endpoint = os.getenv("SAGEMAKER_USE_VPC_ENDPOINT", "false").lower() == "true"
    endpoint_url = os.getenv("SAGEMAKER_VPC_ENDPOINT_URL", "") if use_vpc_endpoint else None

    kwargs: dict[str, Any] = {
        "service_name": "sagemaker-runtime",
        "region_name": region,
        "config": SAGEMAKER_CONFIG,
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    return boto3.client(**kwargs)


def _build_classifier_prompt(query: str) -> str:
    system_prompt = (
        "You are an automotive intent classifier. Classify the user's query into exactly one category:\n"
        "1. CAR_CONTROL: Commands to directly control car hardware (e.g., AC, lights, windows).\n"
        "2. RAG_SEARCH: Questions asking for instructions, how-tos, manuals, troubleshooting, or technical vehicle info.\n"
        "3. FREE_TALK: General conversation, greetings, or unrelated questions.\n"
        "Output ONLY the category name in raw text. Do not output markdown, punctuation, or any other text."
    )
    return f"{system_prompt}\n\nQuery: {query}\nCategory:"


def _parse_generated_text(response_body: Any) -> str:
    """Extract generated text from the vLLM/TGI response payload."""
    if isinstance(response_body, bytes):
        response_body = json.loads(response_body.decode("utf-8"))

    # HF TGI/vLLM container may return either {"generated_text": "..."} or a list.
    if isinstance(response_body, dict):
        text = response_body.get("generated_text", "")
    elif isinstance(response_body, list) and response_body:
        first = response_body[0]
        text = first.get("generated_text", "") if isinstance(first, dict) else str(first)
    else:
        text = str(response_body)

    return text.strip()


def invoke_llm_endpoint(prompt: str, endpoint_name: str | None = None) -> str:
    """Invoke the SageMaker LLM endpoint and return the generated text."""
    endpoint_name = endpoint_name or os.getenv("SAGEMAKER_LLM_ENDPOINT_NAME", "")
    if not endpoint_name:
        raise ValueError("SAGEMAKER_LLM_ENDPOINT_NAME is not set")

    client = get_sagemaker_runtime_client()
    body = json.dumps({"inputs": prompt})

    response = client.invoke_endpoint(
        EndpointName=endpoint_name,
        Body=body,
        ContentType="application/json",
        Accept="application/json",
    )

    response_body = response["Body"].read()
    return _parse_generated_text(response_body)


def classify_intent_with_sagemaker(query: str, endpoint_name: str | None = None) -> str:
    """Classify the query intent using the local SageMaker LLM endpoint.

    Falls back to FREE_TALK if the endpoint is unreachable or returns an
    unexpected category.
    """
    endpoint_name = endpoint_name or os.getenv("SAGEMAKER_LLM_ENDPOINT_NAME", "")
    if not endpoint_name:
        return "FREE_TALK"

    prompt = _build_classifier_prompt(query)
    try:
        raw_text = invoke_llm_endpoint(prompt, endpoint_name)
    except (BotoCoreError, ClientError) as e:
        print(f"[SageMaker Client] Endpoint invocation failed: {e}. Defaulting to FREE_TALK.")
        return "FREE_TALK"

    # Take the first token/word of the response and normalize it.
    first_token = raw_text.split()[0].upper().strip(".,;:!?")
    intent = first_token if first_token in VALID_INTENTS else "FREE_TALK"
    return intent


def invoke_tts_endpoint(text: str, endpoint_name: str | None = None) -> bytes:
    """Placeholder for a future SageMaker TTS endpoint."""
    raise NotImplementedError("TTS endpoint integration is not yet implemented.")
