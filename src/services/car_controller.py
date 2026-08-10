import re
from enum import Enum

from services.text_norm import normalize_utterance


class CommandID(str, Enum):
    DOOR_OPEN = "DOOR_OPEN"
    DOOR_CLOSE = "DOOR_CLOSE"
    MUSIC_PLAY = "MUSIC_PLAY"
    MUSIC_PAUSE = "MUSIC_PAUSE"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    HVAC_ON = "HVAC_ON"
    HVAC_OFF = "HVAC_OFF"
    GENERIC_CONTROL = "GENERIC_CONTROL"


# Patterns assume normalize_utterance() was applied (tone-free VI + lowercase).
# --- START MODIFICATION ---
# Mixed VI/EN + volume vs temp: volume requires volume/am luong; HVAC covers air conditioner / bat ac.
COMMAND_CONTRACTS = [
    # Door / window (window mocked as DOOR_OPEN for Sprint 2 cockpit)
    (
        r"mo\s*.*cua|open\s*.*door|open\s*.*window|open\s+it(?:\s+now)?\b",
        CommandID.DOOR_OPEN,
    ),
    (r"dong\s*.*cua|close\s*.*door|close\s*.*window", CommandID.DOOR_CLOSE),
    # Music & volume (volume keyword required — not bare "van ... do/c")
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
    # HVAC — pure VI + mixed loanwords (bat air conditioner, turn on dieu hoa)
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


def get_command_id(query: str, *, normalized: str | None = None) -> str:
    """Return command ID contract for cockpit mock actuation.

    Always matches against normalized text (ingress fold) to avoid
    diacritic / casing drift vs the intent router.
    """
    # --- START MODIFICATION ---
    text = normalized if normalized is not None else normalize_utterance(query)
    for pattern, cmd_id in COMPILED_CONTRACTS:
        if pattern.search(text):
            return cmd_id.value
    return DEFAULT_COMMAND_ID
    # --- END MODIFICATION ---
