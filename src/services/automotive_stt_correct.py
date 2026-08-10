"""Deterministic automotive STT typo / phonetic repair (sub-ms, no LLM).

Rewrites common Google STT mishears of OEM acronyms before intent + RAG.
Python is the source of truth; cockpit mirrors the same seed table in Kotlin.
"""

from __future__ import annotations

import re
from typing import Iterable

# Manuals-first canonical allowlist (docs_pdf + existing OEM synonyms).
CANONICAL_ACRONYMS: frozenset[str] = frozenset(
    {
        "epb",
        "hvac",
        "adas",
        "aeb",
        "abs",
        "tpms",
        "isofix",
        "latch",
        "obd",
        "esc",
        "ldw",
        "lka",
        "bsm",
        "scc",
        "fca",
        "avn",
        "ics",
        "mil",
        "mist",
        "eco",
        "ev",
        "vdc",
        "rcta",
        "bcw",
        "svm",
    }
)

# Explicit phonetic / typo map (folded lowercase → canonical).
# Longer / multi-word keys are applied first.
_EXPLICIT_MAP: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            ("electronic parking brake", "epb"),
            ("air conditioner", "hvac"),
            ("aitch vac", "hvac"),
            ("iso fix", "isofix"),
            ("tee pms", "tpms"),
            ("tp ms", "tpms"),
            ("t p m s", "tpms"),
            ("a das", "adas"),
            ("a-das", "adas"),
            ("a e b", "aeb"),
            ("a b s", "abs"),
            ("e p b", "epb"),
            ("h vac", "hvac"),
            ("o b d", "obd"),
            ("obd2", "obd"),
            ("obdii", "obd"),
            ("hvec", "hvac"),
            ("hvacx", "hvac"),
            ("epp", "epb"),
            ("ebp", "epb"),
            ("adass", "adas"),
            ("tpms", "tpms"),
            ("isofix", "isofix"),
            ("hvac", "hvac"),
            ("epb", "epb"),
            ("adas", "adas"),
            ("aeb", "aeb"),
            ("abs", "abs"),
            ("obd", "obd"),
        ),
        key=lambda kv: -len(kv[0]),
    )
)

# Everyday tokens that must NEVER be rewritten via edit-distance.
_COMMON_WORD_STOP: frozenset[str] = frozenset(
    {
        # EN
        "app",
        "map",
        "can",
        "car",
        "bus",
        "has",
        "was",
        "his",
        "her",
        "the",
        "and",
        "for",
        "are",
        "you",
        "all",
        "any",
        "how",
        "who",
        "why",
        "what",
        "when",
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "will",
        "just",
        "like",
        "make",
        "take",
        "help",
        "open",
        "close",
        "turn",
        "play",
        "stop",
        "next",
        "back",
        "door",
        "lock",
        "temp",
        "heat",
        "cool",
        "air",
        "fan",
        "off",
        "on",
        # VI (tone-free)
        "toi",
        "ban",
        "cua",
        "cho",
        "voi",
        "nay",
        "kia",
        "sao",
        "the",
        "nao",
        "giup",
        "lam",
        "bat",
        "tat",
        "mo",
        "dong",
        "van",
        "len",
        "xuong",
        "nhac",
        "nhiet",
        "do",
        "phanh",
        "guong",
        "dieu",
        "hoa",
        "may",
        "lanh",
    }
)

_SPACED_LETTERS = re.compile(
    r"(?<![a-z0-9])(?:[a-z](?:\s+[a-z]){1,5})(?![a-z0-9])",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _collapse_spaced_letters(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Collapse runs like 'e p b' / 'E P B' into 'epb'."""
    fixes: list[tuple[str, str]] = []

    def _repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        collapsed = re.sub(r"\s+", "", raw).lower()
        if " " in raw and collapsed:
            fixes.append((raw, collapsed))
        return collapsed

    out = _SPACED_LETTERS.sub(_repl, text)
    return out, fixes


def _apply_explicit_map(text: str) -> tuple[str, list[tuple[str, str]]]:
    fixes: list[tuple[str, str]] = []
    out = text
    lowered = out.lower()
    for src, dst in _EXPLICIT_MAP:
        if src == dst:
            continue
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(src)}(?![a-z0-9])", re.IGNORECASE)
        if not pattern.search(out):
            continue
        out, n = pattern.subn(dst, out)
        if n:
            fixes.append((src, dst))
            lowered = out.lower()
    return out, fixes


def _guarded_edit_distance(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite short unknown tokens within distance 1 of exactly one acronym."""
    fixes: list[tuple[str, str]] = []
    parts: list[str] = []
    last = 0
    for match in _TOKEN.finditer(text):
        parts.append(text[last : match.start()])
        token = match.group(0)
        low = token.lower()
        replacement = token
        if (
            low.isalpha()
            and 3 <= len(low) <= 5
            and low not in CANONICAL_ACRONYMS
            and low not in _COMMON_WORD_STOP
        ):
            hits = [c for c in CANONICAL_ACRONYMS if _levenshtein(low, c) == 1]
            if len(hits) == 1:
                replacement = hits[0]
                fixes.append((low, hits[0]))
        parts.append(replacement)
        last = match.end()
    parts.append(text[last:])
    return "".join(parts), fixes


def correct_automotive_stt(text: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Correct automotive STT mishears.

    Returns (corrected_text, list of (from, to) fixes applied).
    """
    # --- START MODIFICATION ---
    if not text or not text.strip():
        return text or "", []

    all_fixes: list[tuple[str, str]] = []
    out = text.strip()

    out, spaced = _collapse_spaced_letters(out)
    all_fixes.extend(spaced)

    out, mapped = _apply_explicit_map(out)
    all_fixes.extend(mapped)

    out, fuzzy = _guarded_edit_distance(out)
    all_fixes.extend(fuzzy)

    # Preserve original casing style lightly: keep as lowercase for routing stability
    # but restore if no change.
    if not all_fixes:
        return text, []

    # Prefer returning corrected with original surrounding whitespace trimmed only
    return out, all_fixes
    # --- END MODIFICATION ---


def format_fixes(fixes: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{a}→{b}" for a, b in fixes)
