import re
import time
import unicodedata

from dotenv import load_dotenv

import sagemaker_client

# Load environment variables from .env
load_dotenv()


CAR_CONTROL_REGEX = (
    r"\b(bat|tat|mo|dong|tang|giam|chinh|keo|len|xuong)\b.*"
    r"\b(dieu hoa|hvac|den|den pha|den hau|cua|kinh|nhac|am luong|quat|gio|"
    r"nhiet do|ghe|cop|suoi)\b"
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
    Production hot-path classifier: regex only, no LLM round-trip.
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
    Falls back to the dedicated SageMaker LLM endpoint if regex results in FREE_TALK.
    Returns: (INTENT_STRING, latency_ms)

    NOTE: Gateway production path should use classify_intent_fast() to avoid
    any LLM round-trip overhead on every turn.
    """
    start_time = time.perf_counter()

    # 1. Fast Path: Check Regex First
    intent = classify_intent_by_regex(query)

    # If Regex identifies a specific action, return it immediately
    if intent != "FREE_TALK":
        latency = int((time.perf_counter() - start_time) * 1000)
        return intent, latency

    # 2. Slow Path: Fallback to the dedicated SageMaker LLM endpoint
    intent = sagemaker_client.classify_intent_with_sagemaker(query)

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
