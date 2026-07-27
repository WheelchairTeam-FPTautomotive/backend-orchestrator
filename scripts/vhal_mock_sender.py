import argparse
import json
import time
import sys

def main():
    parser = argparse.ArgumentParser(description="CarSky VHAL Signal Simulator Client")
    parser.add_argument("--speed", type=float, default=60.0, help="Simulated vehicle speed in km/h")
    parser.add_argument("--ac-on", action="store_true", help="Simulated air conditioning status (HVAC)")
    parser.add_argument("--interval", type=float, default=1.0, help="Signal publish interval in seconds")
    parser.add_argument("--steps", type=int, default=10, help="Number of simulated steps to emit")
    args = parser.parse_args()

    # Property ID definitions matching Car API and VHAL stubs
    PERF_VEHICLE_SPEED_ID = "0x11600207"  # VehiclePropertyIds.PERF_VEHICLE_SPEED
    HVAC_AC_ON_ID = "0x15200505"         # VehiclePropertyIds.HVAC_AC_ON

    print("==========================================================")
    print("CarSky simulated VHAL Server running...")
    print(f"Target initial speed: {args.speed} km/h")
    print(f"Target HVAC state: {'ON' if args.ac_on else 'OFF'}")
    print("==========================================================")

    current_speed = args.speed
    ac_state = args.ac_on

    for step in range(1, args.steps + 1):
        if step > 2:
            current_speed += (step % 3 - 1) * 2.5
            
        payload = {
            "timestamp_ns": int(time.time() * 1e9),
            "events": [
                {
                    "property_id": PERF_VEHICLE_SPEED_ID,
                    "area_id": 0,
                    "value": float(current_speed),
                    "type": "Float"
                },
                {
                    "property_id": HVAC_AC_ON_ID,
                    "area_id": 0,
                    "value": bool(ac_state),
                    "type": "Boolean"
                }
            ]
        }

        print(f"[Step {step:02d}/{args.steps:02d}] Emitting VHAL signals:")
        print(json.dumps(payload, indent=2))
        print("-" * 40)
        time.sleep(args.interval)

    print("VHAL signal simulation run completed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulation aborted by user.")
        sys.exit(0)
