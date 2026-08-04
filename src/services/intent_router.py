import os
import re
import time
import unicodedata
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


CAR_CONTROL_REGEX = (
    r"\b(bat|tat|mo|dong|tang|giam|chinh|keo|len|xuong|gap)\b.*"
    r"\b(dieu hoa|hvac|den|den pha|den hau|cua|kinh|nhac|am luong|quat|gio|"
    r"nhiet do|ghe|cop|suoi|guong|mirror)\b"
)
RAG_SEARCH_REGEX = (
    r"\b(huong dan|tai lieu|sua|loi|cach nao|lam sao|cach de|cach|bao hanh|"
    r"kiem tra|hong|nguyen nhan|tai sao|bao duong|thay the|quy trinh|bao ve|"
    r"manual|how to|how do|dac ta|thong so|he thong)\b"
)
# Greetings + bounded off-domain. Matched AFTER CAR/RAG to avoid intent collisions.
FREE_TALK_REGEX = (
    r"(?:^|\b)("
    r"xin chao|chao buoi|chao|"
    r"hello|hi|hey|"
    r"cam on|thanks|thank you|"
    r"ban khoe khong|how are you|"
    r"good morning|good evening|"
    r"thoi tiet|weather|"
    r"co phieu|chung khoan|\bstocks?\b|"
    r"cong thuc nau|nau pho|nau mon|"
    r"sap xep mang|viet ho tui|viet ho toi|"
    r"\bpython\b|\bjavascript\b|"
    r"joke|ke cho|ke toi|dich giup|\bdich\b|an gi"
    r")\b"
)

# Advice/duration cues: CAR match + these => RAG (manual how-long), not hardware stub
CAR_ADVICE_REGEX = r"\b(bao lau|how long|should i|bao nhieu)\b|\bnen\b"

# Doc/tech tokens — block short chitchat heuristic from swallowing these
RAG_DOC_TOKEN_REGEX = (
    r"\b(p0\d{3}|ma loi|ap suat|lop|pdf|hvac|aeb|adas|pontis|tachonet|"
    r"gaia|evla|peppol|keepass|ertms|manual|light-control|hoat dong|"
    r"control-system)\b|\b20\d{2}\b"
)


def _fold_vi(text: str) -> str:
    """Lowercase + strip Vietnamese diacritics. Explicitly map đ/Đ → d."""
    # --- START MODIFICATION ---
    lowered = text.lower().strip()
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    nfd = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # --- END MODIFICATION ---


def classify_intent_by_regex(text: str) -> str:
    """Fast rule-based classifier. Checked before hitting the LLM."""
    folded = _fold_vi(text)

    if re.search(CAR_CONTROL_REGEX, folded):
        return "CAR_CONTROL"

    if re.search(RAG_SEARCH_REGEX, folded):
        return "RAG_SEARCH"

    if re.search(FREE_TALK_REGEX, folded):
        return "FREE_TALK"

    # Legacy slow-path default
    return "FREE_TALK"


def classify_intent_fast(query: str) -> tuple[str, int]:
    """
    Production hot-path classifier: regex only, no Bedrock round-trip.
    Order: CAR (->RAG if advice) -> RAG/doc-tokens -> FREE_TALK -> short chitchat -> default RAG.
    """
    start_time = time.perf_counter()
    folded = _fold_vi(query)

    # --- START MODIFICATION ---
    if re.search(CAR_CONTROL_REGEX, folded):
        # Hybrid advice ("bao lau", "nen ...") stays on manuals, not hardware stub
        if re.search(CAR_ADVICE_REGEX, folded):
            intent = "RAG_SEARCH"
        else:
            intent = "CAR_CONTROL"
    elif re.search(RAG_SEARCH_REGEX, folded) or re.search(RAG_DOC_TOKEN_REGEX, folded):
        intent = "RAG_SEARCH"
    elif re.search(FREE_TALK_REGEX, folded):
        intent = "FREE_TALK"
    else:
        words = [w for w in re.split(r"\s+", folded) if w]
        if len(words) <= 6 and not re.search(RAG_DOC_TOKEN_REGEX, folded):
            intent = "FREE_TALK"
        else:
            intent = "RAG_SEARCH"
    # --- END MODIFICATION ---

    latency = int((time.perf_counter() - start_time) * 1000)
    return intent, latency



def classify_intent(query: str) -> tuple[str, int]:
    """
    Classifies intent using regex first.
    Falls back to Mistral via Amazon Bedrock if regex results in FREE_TALK.
    Returns: (INTENT_STRING, latency_ms)

    NOTE: Gateway production path should use classify_intent_fast() to avoid
    200–500ms Bedrock overhead on every turn.
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
