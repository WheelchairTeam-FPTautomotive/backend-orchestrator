"""Unsafe / jailbreak utterance detection for control-bus protection."""

from __future__ import annotations

import re

from services.text_norm import normalize_utterance

# --- START MODIFICATION ---
# Precedence: these must never emit command_id (Safety > CAR).
_JAILBREAK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\s+previous\b",
        r"\bignore\s+all\s+(?:previous\s+)?instructions?\b",
        r"\bjailbreak\b",
        r"\bbypass\s+(?:the\s+)?(?:brake|brakes|aeb|abs|safety)\b",
        r"\bdisable\s+(?:aeb|abs|airbag|seatbelt)\b",
        r"\boverdrive\s+engine\b",
        r"\bhack\b.*\b(ecu|can|brake|door)\b",
        r"\bbo\s+qua\s+(?:lenh|huong\s+dan)\b",
    )
)

# Explicit safety-override language (EN + tone-free VI)
_SAFETY_OVERRIDE = re.compile(
    r"(?:"
    r"ignore\s+all\s+safety"
    r"|ignore\s+.*\bsafety\s+protocols?"
    r"|bypass\s+.*\bsafety"
    r"|bo\s+qua\s+(?:canh\s+bao\s+)?an\s+toan"
    r"|bo\s+qua\s+canh\s+bao"
    r")",
    re.IGNORECASE,
)

# Vehicle in motion / highway cues
_MOVING = re.compile(
    r"(?:"
    r"\bwhile\s+(?:the\s+)?(?:car|vehicle)\s+is\s+moving\b"
    r"|\bwhile\s+driving\b"
    r"|\bin\s+motion\b"
    r"|\bcao\s+toc\b"
    r"|\bdang\s+di\b"
    r"|\bdang\s+lai\b"
    r"|\bdi\s+tren\s+duong\b"
    r")",
    re.IGNORECASE,
)

# Actuators that must not open/lower while moving or after safety override
_ACTUATOR_OPEN = re.compile(
    r"(?:"
    r"\bopen\s+(?:the\s+)?(?:door|trunk|window|hood)\b"
    r"|\bmo\s+(?:cua|cop|kinh|cua\s+so)\b"
    r"|\bha\s+kinh\b"
    r"|\blower\s+(?:the\s+)?window\b"
    r"|\bunlock\b"
    r")",
    re.IGNORECASE,
)

# Back-compat name used by older tests / docs
UNSAFE_PATTERNS = _JAILBREAK_PATTERNS


def is_unsafe_utterance(query: str, *, normalized: str | None = None) -> bool:
    """True when utterance must be refused (no CAR, no free-talk handoff)."""
    folded = normalized if normalized is not None else normalize_utterance(query)
    if not folded:
        return False

    if any(p.search(folded) for p in _JAILBREAK_PATTERNS):
        return True

    # Safety override + any door/trunk/window actuation
    if _SAFETY_OVERRIDE.search(folded) and _ACTUATOR_OPEN.search(folded):
        return True

    # Standalone "ignore all safety" even without explicit actuator (pack EN-3 style)
    if _SAFETY_OVERRIDE.search(folded):
        return True

    # Moving / highway + open/lower actuator
    if _MOVING.search(folded) and _ACTUATOR_OPEN.search(folded):
        return True

    return False


# --- END MODIFICATION ---
