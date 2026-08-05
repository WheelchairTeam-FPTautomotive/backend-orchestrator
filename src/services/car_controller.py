import re
from enum import Enum

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

# Centralized Mapping: (Pattern, Command ID)
COMMAND_CONTRACTS = [
    # Door Controls
    (r"mở.*cửa|open.*door", CommandID.DOOR_OPEN),
    (r"đóng.*cửa|close.*door", CommandID.DOOR_CLOSE),
    # Music & Volume Controls
    (r"bật.*nhạc|phát.*nhạc|play.*music", CommandID.MUSIC_PLAY),
    (r"tắt.*nhạc|dừng.*nhạc|pause.*music|stop.*music", CommandID.MUSIC_PAUSE),
    (r"tăng.*âm lượng|to lên|volume up", CommandID.VOLUME_UP),
    (r"giảm.*âm lượng|nhỏ đi|volume down", CommandID.VOLUME_DOWN),
    # HVAC Controls
    (r"bật.*điều hòa|mở.*điều hòa|ac on|hvac on", CommandID.HVAC_ON),
    (r"tắt.*điều hòa|ac off|hvac off", CommandID.HVAC_OFF),
]

# Pre-compile regexes for optimal execution performance
COMPILED_CONTRACTS = [
    (re.compile(pattern, re.IGNORECASE), cmd_id)
    for pattern, cmd_id in COMMAND_CONTRACTS
]

DEFAULT_COMMAND_ID = "GENERIC_CONTROL"


def get_command_id(query: str) -> str:
    """Parses a car control query to return a standardized command ID contract.

    This contract is shared with the Android Cockpit UI for mocking
    animations.
    """
    for pattern, cmd_id in COMPILED_CONTRACTS:
        if pattern.search(query):
            return cmd_id

    return DEFAULT_COMMAND_ID