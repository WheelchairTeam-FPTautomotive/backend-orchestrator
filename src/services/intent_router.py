import re
import time

from dotenv import load_dotenv

from services import sagemaker_client
from services.car_controller import DEFAULT_COMMAND_ID, get_command_id
from services.text_norm import normalize_utterance

# Load environment variables from .env
load_dotenv()

# Re-export for tests / callers
_fold_vi = normalize_utterance

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

# Advice/duration cues: alone with control vocab => RAG (manual), not hardware
CAR_ADVICE_REGEX = r"\b(bao lau|how long|should i|bao nhieu)\b|\bnen\b"

RAG_DOC_TOKEN_REGEX = (
    r"\b(p0\d{3}|ma loi|ap suat|lop|pdf|hvac|aeb|adas|pontis|tachonet|"
    r"gaia|evla|peppol|keepass|ertms|manual|light-control|hoat dong|"
    r"control-system)\b|\b20\d{2}\b"
)


def _has_trailing_imperative(normalized: str) -> bool:
    """True when a later clause is a direct control command (compound utterances)."""
    # --- START MODIFICATION ---
    parts = [p.strip() for p in re.split(r"[?.!]+", normalized) if p.strip()]
    if len(parts) < 2:
        return False
    return get_command_id(parts[-1], normalized=parts[-1]) != DEFAULT_COMMAND_ID
    # --- END MODIFICATION ---


def classify_intent_by_regex(text: str) -> str:
    """Fast rule-based classifier. Checked before hitting the LLM."""
    folded = normalize_utterance(text)

    if re.search(CAR_CONTROL_REGEX, folded):
        return "CAR_CONTROL"

    if re.search(RAG_SEARCH_REGEX, folded):
        return "RAG_SEARCH"

    if re.search(FREE_TALK_REGEX, folded):
        return "FREE_TALK"

    return "FREE_TALK"


def classify_intent_fast(
    query: str, *, normalized: str | None = None
) -> tuple[str, int]:
    """
    Production hot-path classifier: regex only, no LLM round-trip.

    Precedence (locked #20):
      Direct control (known command_id) > RAG heuristics > Free talk
    Advice hybrid (should i / bao lau) stays RAG unless a trailing imperative
    control clause is present (compound utterances).
    """
    start_time = time.perf_counter()
    folded = normalized if normalized is not None else normalize_utterance(query)

    # --- START MODIFICATION ---
    # 1) Direct control via shared command contract (single source of truth)
    cmd_id = get_command_id(folded, normalized=folded)
    if cmd_id != DEFAULT_COMMAND_ID:
        if re.search(CAR_ADVICE_REGEX, folded) and not _has_trailing_imperative(folded):
            intent = "RAG_SEARCH"
        else:
            intent = "CAR_CONTROL"
    elif re.search(CAR_CONTROL_REGEX, folded):
        # Legacy VI verb/object CAR without a mapped command_id → still CAR
        # (gateway will warn on GENERIC_CONTROL)
        if re.search(CAR_ADVICE_REGEX, folded) and not _has_trailing_imperative(folded):
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

    intent = classify_intent_by_regex(query)

    if intent != "FREE_TALK":
        latency = int((time.perf_counter() - start_time) * 1000)
        return intent, latency

    intent = sagemaker_client.classify_intent_with_sagemaker(query)

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    return intent, latency_ms


if __name__ == "__main__":
    print("=== Testing Intent Classifier Service ===")

    test_queries = [
        "Bật đèn pha cho tôi",
        "Làm cách nào để bật hệ thống điều hòa HVAC trên buồng lái?",
        "Xin chào, bạn khỏe không?",
        "Làm sao để thay lốp xe bị thủng?",
        "Tăng âm lượng nhạc lên chút nhé",
        "Hey Car, open the door",
    ]

    for q in test_queries:
        intent_result, ms = classify_intent_fast(q)
        print(f"Query: '{q}'")
        print(f"-> Intent: {intent_result} (Latency: {ms}ms)\n")
