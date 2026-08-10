import re
from enum import Enum

from services.text_norm import normalize_utterance


class CommandID(str, Enum):
    DOOR_OPEN = "DOOR_OPEN"
    DOOR_CLOSE = "DOOR_CLOSE"
    TRUNK_OPEN = "TRUNK_OPEN"
    TRUNK_CLOSE = "TRUNK_CLOSE"
    WINDOW_OPEN = "WINDOW_OPEN"
    WINDOW_CLOSE = "WINDOW_CLOSE"
    MUSIC_PLAY = "MUSIC_PLAY"
    MUSIC_PAUSE = "MUSIC_PAUSE"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    HVAC_ON = "HVAC_ON"
    HVAC_OFF = "HVAC_OFF"
    HVAC_TEMP_SET = "HVAC_TEMP_SET"
    GENERIC_CONTROL = "GENERIC_CONTROL"


# Automotive HVAC set-point bounds (Wave 1B guardrail)
TEMP_C_MIN = 16.0
TEMP_C_MAX = 30.0
TEMP_F_MIN = 60.0
TEMP_F_MAX = 85.0

_TEMP_VALUE = re.compile(
    r"(?:set|chinh|dat|van)?\s*.*(?:temp(?:erature)?|nhiet\s*do|dieu\s*hoa|hvac|ac)\s*"
    r".*?(\d{1,3})\s*(?:do|degrees?|c|f)?|"
    r"(\d{1,3})\s*(?:do|degrees?|c)\b",
    re.IGNORECASE,
)


def parse_hvac_temp_celsius(text: str) -> float | None:
    """
    Extract a temperature set-point and validate automotive bounds.
    Returns Celsius float when valid; None when absent or out of range.
    """
    # --- START MODIFICATION ---
    folded = normalize_utterance(text)
    m = _TEMP_VALUE.search(folded)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None

    # Heuristic: >40 → Fahrenheit
    if value > 40:
        if value < TEMP_F_MIN or value > TEMP_F_MAX:
            return None
        return round((value - 32.0) * 5.0 / 9.0, 1)

    if value < TEMP_C_MIN or value > TEMP_C_MAX:
        return None
    return value
    # --- END MODIFICATION ---


# Patterns assume normalize_utterance() was applied (tone-free VI + lowercase).
# --- START MODIFICATION ---
# Order matters: trunk/window/temp before generic door (cop ≠ cua).
COMMAND_CONTRACTS = [
    # Trunk / cốp — before door
    (
        r"mo\s*cop|open\s*(?:the\s+)?trunk|mo\s*cappo|open\s*(?:the\s+)?boot",
        CommandID.TRUNK_OPEN,
    ),
    (
        r"dong\s*cop|close\s*(?:the\s+)?trunk|close\s*(?:the\s+)?boot",
        CommandID.TRUNK_CLOSE,
    ),
    # Window / cửa sổ — before generic door
    (
        r"mo\s*.*cua\s*so|ha\s*kinh|open\s*(?:the\s+)?window|lower\s*(?:the\s+)?window",
        CommandID.WINDOW_OPEN,
    ),
    (
        r"dong\s*.*cua\s*so|len\s*kinh|close\s*(?:the\s+)?window|raise\s*(?:the\s+)?window",
        CommandID.WINDOW_CLOSE,
    ),
    # Door (exclude cốp / cửa sổ via negative lookahead on cop)
    (
        r"mo\s*.*cua(?!\s*so)|open\s*.*door|open\s+it(?:\s+now)?\b",
        CommandID.DOOR_OPEN,
    ),
    (
        r"dong\s*.*cua(?!\s*so)|close\s*.*door",
        CommandID.DOOR_CLOSE,
    ),
    # Music & volume
    (r"bat\s*.*nhac|phat\s*.*nhac|play\s*.*music", CommandID.MUSIC_PLAY),
    (
        r"tat\s*.*nhac|dung\s*.*nhac|pause\s*.*music|stop\s*.*music",
        CommandID.MUSIC_PAUSE,
    ),
    (
        r"(?:giam|nho\s+di).*(?:am\s*luong|volume)"
        r"|(?:am\s*luong|volume).*(?:xuong|down|giam)"
        r"|van\s+.*(?:am\s*luong|volume).*(?:xuong|down|giam)"
        r"|volume\s+down",
        CommandID.VOLUME_DOWN,
    ),
    (
        r"(?:tang|to\s+len).*(?:am\s*luong|volume)"
        r"|(?:am\s*luong|volume).*(?:len|up|tang)"
        r"|van\s+.*(?:am\s*luong|volume).*(?:len|up|tang)"
        r"|volume\s+up",
        CommandID.VOLUME_UP,
    ),
    # HVAC temp set (checked via parse_hvac_temp_celsius in get_command_id)
    # HVAC on/off — mixed loanwords
    (
        r"bat\s*.*(?:dieu\s*hoa|may\s*lanh|air\s*conditioner|\bac\b|hvac)"
        r"|mo\s*.*(?:dieu\s*hoa|may\s*lanh|air\s*conditioner|\bac\b|hvac)"
        r"|turn\s+on\s*.*(?:dieu\s*hoa|may\s*lanh|air\s*conditioner|\bac\b|hvac)"
        r"|\bac\s+on\b|\bhvac\s+on\b",
        CommandID.HVAC_ON,
    ),
    (
        r"tat\s*.*(?:dieu\s*hoa|may\s*lanh|air\s*conditioner|\bac\b|hvac)"
        r"|turn\s+off\s*.*(?:dieu\s*hoa|may\s*lanh|air\s*conditioner|\bac\b|hvac)"
        r"|\bac\s+off\b|\bhvac\s+off\b",
        CommandID.HVAC_OFF,
    ),
]
# --- END MODIFICATION ---

COMPILED_CONTRACTS = [
    (re.compile(pattern, re.IGNORECASE), cmd_id)
    for pattern, cmd_id in COMMAND_CONTRACTS
]

DEFAULT_COMMAND_ID = CommandID.GENERIC_CONTROL.value

_TEMP_SET_CUE = re.compile(
    r"(?:"
    r"set\s+.*(?:temp|temperature)"
    r"|nhiet\s*do"
    r"|temperature\s+to"
    r"|\d+\s*(?:do|degrees?|c)\b"
    r")",
    re.IGNORECASE,
)


def has_temp_set_cue(text: str) -> bool:
    """True when utterance looks like a temperature set-point request."""
    return bool(_TEMP_SET_CUE.search(text))


def get_command_id(query: str, *, normalized: str | None = None) -> str:
    """Return command ID contract for cockpit mock actuation.

    Always matches against normalized text (ingress fold) to avoid
    diacritic / casing drift vs the intent router.
    """
    # --- START MODIFICATION ---
    text = normalized if normalized is not None else normalize_utterance(query)

    # Temperature set — only when in-bounds parse succeeds
    if has_temp_set_cue(text):
        temp_c = parse_hvac_temp_celsius(text)
        if temp_c is not None:
            return CommandID.HVAC_TEMP_SET.value
        # Out-of-range or missing number with temp cue → not a valid control
        # (intent may still be CAR; gateway soft-rejects). Fall through.

    for pattern, cmd_id in COMPILED_CONTRACTS:
        if pattern.search(text):
            return cmd_id.value
    return DEFAULT_COMMAND_ID
    # --- END MODIFICATION ---
