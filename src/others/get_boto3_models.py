import boto3
import os
from dotenv import load_dotenv

load_dotenv()

bedrock = boto3.client("bedrock", region_name=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2"))

# Fetch all active text models in the region
response = bedrock.list_foundation_models(byOutputModality="TEXT")

print("=== AVAILABLE TEXT MODELS IN YOUR ACCOUNT ===")
for model in response.get("modelSummaries", []):
    model_id = model.get("modelId")
    provider = model.get("providerName")
    name = model.get("modelName")
    print(f"[{provider}] {name} -> Model ID: {model_id}")