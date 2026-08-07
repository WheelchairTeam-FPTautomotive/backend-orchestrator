"""Shared utterance normalization for intent + command routing."""

from __future__ import annotations

import unicodedata


def normalize_utterance(text: str) -> str:
    """
    Lowercase + strip Vietnamese diacritics (đ/Đ → d).

    Used at gateway ingress so router and get_command_id see the same string.
    Keep the raw utterance separately for logs / TTS / UI echo.
    """
    # --- START MODIFICATION ---
    lowered = (text or "").lower().strip()
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    nfd = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # --- END MODIFICATION ---


# Back-compat alias
_fold_vi = normalize_utterance
