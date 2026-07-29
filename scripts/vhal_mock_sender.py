"""
CarSky VHAL Signal Simulator Client.

Continuously generates and broadcasts simulated Vehicle Hardware Abstraction Layer
(VHAL) property changes. This is intended for local development and integration
testing of the backend orchestrator and the AAOS cockpit UI.

Run directly:
    python scripts/vhal_mock_sender.py --speed-pattern sawtooth --hvac-pattern toggle

The script imports the project's shared logging configuration, so it must be run
from the repository root or with the repository root on PYTHONPATH.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from typing import Any

# Allow direct execution from the scripts/ directory by adding the project root.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.logging_config import setup_logging


# -----------------------------------------------------------------------------
# VHAL property IDs used by the AAOS cockpit client.
# -----------------------------------------------------------------------------
PERF_VEHICLE_SPEED_ID = "0x11600207"  # VehiclePropertyIds.PERF_VEHICLE_SPEED
HVAC_AC_ON_ID = "0x15200505"          # VehiclePropertyIds.HVAC_AC_ON
AREA_ID_GLOBAL = 0

# Safety threshold observed by the cockpit UI.
SPEED_WARNING_THRESHOLD_KMH = 80.0


# -----------------------------------------------------------------------------
# Signal generation strategies
# -----------------------------------------------------------------------------
def next_speed(
    current: float,
    pattern: str,
    speed_min: float,
    speed_max: float,
    speed_step: float,
    step_index: int,
) -> float:
    """Return the next simulated speed value based on the selected pattern."""
    if pattern == "constant":
        return current

    if pattern == "random":
        new_speed = random.uniform(speed_min, speed_max)
    elif pattern == "ramp":
        new_speed = current + speed_step
        if new_speed > speed_max:
            new_speed = speed_min
    elif pattern == "sawtooth":
        new_speed = current + speed_step
        if new_speed > speed_max:
            new_speed = speed_min
    else:
        raise ValueError(f"Unsupported speed pattern: {pattern}")

    # Clamp to the configured range.
    return float(max(speed_min, min(speed_max, new_speed)))


def next_hvac(current: bool, pattern: str, step_index: int) -> bool:
    """Return the next simulated HVAC state based on the selected pattern."""
    if pattern == "constant-on":
        return True
    if pattern == "constant-off":
        return False
    if pattern == "toggle":
        return not current
    if pattern == "random":
        return bool(random.getrandbits(1))
    raise ValueError(f"Unsupported HVAC pattern: {pattern}")


# -----------------------------------------------------------------------------
# Payload construction
# -----------------------------------------------------------------------------
def build_payload(timestamp_ns: int, speed: float, hvac_on: bool) -> dict[str, Any]:
    """Build a VHAL event payload matching the cockpit UI contract."""
    return {
        "timestamp_ns": timestamp_ns,
        "events": [
            {
                "property_id": PERF_VEHICLE_SPEED_ID,
                "area_id": AREA_ID_GLOBAL,
                "value": float(speed),
                "type": "Float",
            },
            {
                "property_id": HVAC_AC_ON_ID,
                "area_id": AREA_ID_GLOBAL,
                "value": bool(hvac_on),
                "type": "Boolean",
            },
        ],
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Broadcast simulated VHAL signals for cockpit integration testing."
    )

    def env_or_default(name: str, default: Any) -> Any:
        return os.getenv(name, default)

    parser.add_argument(
        "--interval",
        type=float,
        default=float(env_or_default("VHAL_INTERVAL", "1.0")),
        help="Seconds between broadcast ticks (env: VHAL_INTERVAL).",
    )
    parser.add_argument(
        "--speed-start",
        type=float,
        default=float(env_or_default("VHAL_SPEED_START", "60.0")),
        help="Initial speed in km/h (env: VHAL_SPEED_START).",
    )
    parser.add_argument(
        "--speed-min",
        type=float,
        default=float(env_or_default("VHAL_SPEED_MIN", "0.0")),
        help="Minimum speed in km/h (env: VHAL_SPEED_MIN).",
    )
    parser.add_argument(
        "--speed-max",
        type=float,
        default=float(env_or_default("VHAL_SPEED_MAX", "120.0")),
        help="Maximum speed in km/h (env: VHAL_SPEED_MAX).",
    )
    parser.add_argument(
        "--speed-step",
        type=float,
        default=float(env_or_default("VHAL_SPEED_STEP", "2.5")),
        help="Speed increment per tick in km/h (env: VHAL_SPEED_STEP).",
    )
    parser.add_argument(
        "--speed-pattern",
        type=str,
        default=env_or_default("VHAL_SPEED_PATTERN", "sawtooth"),
        choices=["sawtooth", "ramp", "random", "constant"],
        help="Speed simulation pattern (env: VHAL_SPEED_PATTERN).",
    )
    parser.add_argument(
        "--hvac-start",
        type=str,
        default=env_or_default("VHAL_HVAC_START", "off"),
        choices=["on", "off"],
        help="Initial HVAC state (env: VHAL_HVAC_START).",
    )
    parser.add_argument(
        "--hvac-pattern",
        type=str,
        default=env_or_default("VHAL_HVAC_PATTERN", "toggle"),
        choices=["toggle", "random", "constant-on", "constant-off"],
        help="HVAC simulation pattern (env: VHAL_HVAC_PATTERN).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=float(env_or_default("VHAL_DURATION", "0")),
        help="Total seconds to run; 0 means run until interrupted (env: VHAL_DURATION).",
    )
    parser.add_argument(
        "--output-format",
        type=str,
        default=env_or_default("VHAL_OUTPUT_FORMAT", "json"),
        choices=["json", "line"],
        help="Payload output format (env: VHAL_OUTPUT_FORMAT).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=env_or_default("LOG_LEVEL", "INFO"),
        help="Logging verbosity (env: LOG_LEVEL).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=env_or_default("LOG_DIR", "logs"),
        help="Directory for rotating log files (env: LOG_DIR).",
    )
    parser.add_argument(
        "--broadcast-mode",
        type=str,
        default=env_or_default("VHAL_BROADCAST_MODE", "stdout"),
        choices=["stdout"],
        help="Broadcast target; currently only stdout is supported (env: VHAL_BROADCAST_MODE).",
    )

    return parser.parse_args()


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    # Set the log level via the environment so the shared logger picks it up.
    os.environ["LOG_LEVEL"] = args.log_level

    logger = setup_logging(
        name="vhal_mock_sender",
        log_dir=args.log_dir,
        log_file="vhal_mock_sender.log",
    )

    logger.info("Starting VHAL mock sender.")
    logger.info(
        "Configuration: interval=%.2fs, speed_pattern=%s, speed_range=[%.1f, %.1f], "
        "hvac_pattern=%s, duration=%.1fs, output_format=%s",
        args.interval,
        args.speed_pattern,
        args.speed_min,
        args.speed_max,
        args.hvac_pattern,
        args.duration,
        args.output_format,
    )

    running = True

    def handle_shutdown(signum: int, _frame: Any) -> None:
        nonlocal running
        logger.info("Received signal %s; shutting down gracefully.", signum)
        running = False

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    current_speed = float(args.speed_start)
    current_hvac = args.hvac_start == "on"
    step_index = 0
    start_time = time.time()
    last_warning_logged = False

    try:
        while running:
            step_index += 1
            timestamp_ns = int(time.time() * 1e9)

            current_speed = next_speed(
                current_speed,
                args.speed_pattern,
                args.speed_min,
                args.speed_max,
                args.speed_step,
                step_index,
            )
            current_hvac = next_hvac(current_hvac, args.hvac_pattern, step_index)

            payload = build_payload(timestamp_ns, current_speed, current_hvac)

            if args.output_format == "json":
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(payload, ensure_ascii=False))

            logger.info(
                "Broadcasted tick %d: speed=%.2f km/h, hvac=%s, property_ids=[%s, %s]",
                step_index,
                current_speed,
                "ON" if current_hvac else "OFF",
                PERF_VEHICLE_SPEED_ID,
                HVAC_AC_ON_ID,
            )

            if current_speed > SPEED_WARNING_THRESHOLD_KMH and not last_warning_logged:
                logger.warning(
                    "Speed %.2f km/h exceeds cockpit warning threshold of %.1f km/h.",
                    current_speed,
                    SPEED_WARNING_THRESHOLD_KMH,
                )
                last_warning_logged = True
            elif current_speed <= SPEED_WARNING_THRESHOLD_KMH:
                last_warning_logged = False

            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                logger.info("Duration limit reached (%.1fs).", args.duration)
                break

            time.sleep(args.interval)

    except Exception as exc:
        logger.exception("VHAL mock sender encountered an error: %s", exc)
        sys.exit(1)
    finally:
        logger.info("VHAL mock sender stopped. Total ticks emitted: %d", step_index)


if __name__ == "__main__":
    main()
