"""Unsafe / jailbreak utterance detection for control-bus protection."""

from __future__ import annotations

import re

from services.text_norm import normalize_utterance

# --- START MODIFICATION ---
# Precedence: these must never emit command_id (Safety > CAR).
UNSAFE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\s+previous\b",
        r"\bignore\s+all\s+(?:previous\s+)?instructions?\b",
        r"\bjailbreak\b",
        r"\bbypass\s+(?:the\s+)?(?:brake|brakes|aeb|abs|safety)\b",
        r"\bdisable\s+(?:aeb|abs|airbag|seatbelt)\b",
        r"\boverdrive\s+engine\b",
        r"\bhack\b.*\b(ecu|can|brake|door)\b",
        r"\bbo\s+qua\s+(?:lenh|huong\s+dan|an\s+toan)\b",
    )
)


def is_unsafe_utterance(query: str, *, normalized: str | None = None) -> bool:
    """True when utterance must be refused (no CAR, no free-talk handoff)."""
    folded = normalized if normalized is not None else normalize_utterance(query)
    if not folded:
        return False
    return any(p.search(folded) for p in UNSAFE_PATTERNS)


# --- END MODIFICATION ---
