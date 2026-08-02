import os
import re
import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

# Configure Boto3 client with a strict timeout to meet the <200ms Acceptance Criteria
# We set connect to 50ms and read to 150ms. If Bedrock takes longer, it throws a TimeoutError.
bedrock_config = Config(
    connect_timeout=5,  
    read_timeout=5,     
    retries={'max_attempts': 0}
)

MODEL_ID = "mistral.ministral-3-3b-instruct"

# Initialize Bedrock client
try:
    bedrock_runtime = boto3.client(
        service_name='bedrock-runtime',
        region_name=REGION,
        config=bedrock_config
    )
except Exception as e:
    print(f"Warning: Failed to initialize Bedrock client: {e}")
    bedrock_runtime = None


CAR_CONTROL_REGEX = r'\b(bật|tắt|mở|đóng|tăng|giảm|chỉnh|kéo|lên|xuống)\b.*\b(điều hòa|hvac|đèn|đèn pha|đèn hậu|cửa|kính|nhạc|âm lượng|quạt|gió|nhiệt độ|ghế|cốp)\b'
RAG_SEARCH_REGEX = r'\b(hướng dẫn|tài liệu|sửa|lỗi|cách nào|làm sao|bảo hành|kiểm tra|hỏng|nguyên nhân|tại sao|bảo dưỡng|thay thế|quy trình)\b'

def classify_intent_by_regex(text: str) -> str:
    """Fast rule-based classifier. Checked before hitting the LLM."""
    text = text.lower()
    
    if re.search(CAR_CONTROL_REGEX, text):
        return "CAR_CONTROL"
        
    elif re.search(RAG_SEARCH_REGEX, text):
        return "RAG_SEARCH"
        
    # Default to Free Talk if no specific pattern matches
    return "FREE_TALK"


def classify_intent(query: str) -> tuple[str, int]:
    """
    Classifies intent using regex first.
    Falls back to Mistral via Amazon Bedrock if regex results in FREE_TALK.
    Returns: (INTENT_STRING, latency_ms)
    """
    start_time = time.perf_counter()
    
    # 1. Fast Path: Check Regex First
    intent = classify_intent_by_regex(query)
    
    # If Regex identifies a specific action, return it immediately
    if intent != "FREE_TALK":
        latency = int((time.perf_counter() - start_time) * 1000)
        return intent, latency
        
    # 2. Slow Path: Fallback to AI Model if Regex couldn't identify it (FREE_TALK)
    if not bedrock_runtime:
        latency = int((time.perf_counter() - start_time) * 1000)
        return "FREE_TALK", latency

    # Claude 3 Messages API payload for Zero-shot routing
    # prompt_payload = {
    #     "anthropic_version": "bedrock-2023-05-31",
    #     "maxTokens": 10,
    #     "temperature": 0.0,
    #     "system": (
    #         "You are an automotive intent classifier. Classify the user's query into exactly one of these three categories:\n"
    #         "1. CAR_CONTROL: Commands to directly control car hardware (e.g., AC, lights, windows).\n"
    #         "2. RAG_SEARCH: Questions asking for instructions, how-tos, manuals, troubleshooting, or technical vehicle info.\n"
    #         "3. FREE_TALK: General conversation, greetings, or unrelated questions.\n"
    #         "Output ONLY the category name. Do not output any other text."
    #     ),
    #     "messages": [
    #         {"role": "user", "content": query}
    #     ]
    # }

    system_prompt = (
        "You are an automotive intent classifier. Classify the user's query into exactly one category:\n"
        "1. CAR_CONTROL: Commands to directly control car hardware (e.g., AC, lights, windows).\n"
        "2. RAG_SEARCH: Questions asking for instructions, how-tos, manuals, troubleshooting, or technical vehicle info.\n"
        "3. FREE_TALK: General conversation, greetings, or unrelated questions.\n"
        "Output ONLY the category name in raw text. Do not output markdown, punctuation, or any other text."
    )

    try:
        # response = bedrock_runtime.invoke_model(
        #     modelId=MODEL_ID,
        #     contentType="application/json",
        #     accept="application/json",
        #     body=json.dumps(prompt_payload)
        # )
        
        # response_body = json.loads(response.get('body').read())
        # Parse standard Anthropic Claude 3 response format
        # intent = response_body.get('content', [{}])[0].get('text', '').strip()
        
        # Converse API works seamlessly with Amazon Nova Micro
        response = bedrock_runtime.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": query}]}],
            system=[{"text": system_prompt}],
            inferenceConfig={
                "maxTokens": 10,
                "temperature": 0.0,
                "topP": 0.9
            }
        )
        
        # Extract response text directly from Converse API structure
        intent = response['output']['message']['content'][0]['text'].strip()

        # Validate output, default to FREE_TALK if hallucinated
        if intent not in ["CAR_CONTROL", "RAG_SEARCH", "FREE_TALK"]:
            intent = "FREE_TALK"
            
    except (BotoCoreError, ClientError) as e:
        # Catch timeouts and network errors safely
        print(f"[Intent Router] Bedrock failed/timed out: {e}. Defaulting to FREE_TALK.")
        intent = "FREE_TALK"
    except Exception as e:
        print(f"[Intent Router] Unexpected error: {e}. Defaulting to FREE_TALK.")
        intent = "FREE_TALK"

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    return intent, latency_ms


if __name__ == "__main__":
    print("=== Testing Intent Classifier Service ===")
    
    test_queries = [
        "Bật đèn pha cho tôi",                                          # Expected: CAR_CONTROL
        "Làm cách nào để bật hệ thống điều hòa HVAC trên buồng lái?",   # Expected: RAG_SEARCH
        "Xin chào, bạn khỏe không?",                                    # Expected: FREE_TALK
        "Làm sao để thay lốp xe bị thủng?",                             # Expected: RAG_SEARCH
        "Tăng âm lượng nhạc lên chút nhé",                              # Expected: CAR_CONTROL
    ]
    
    for q in test_queries:
        intent_result, ms = classify_intent(q)
        print(f"Query: '{q}'")
        print(f"-> Intent: {intent_result} (Latency: {ms}ms)\n")
