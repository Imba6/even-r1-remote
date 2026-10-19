import argparse
import asyncio
import logging
from .ble import Transport
from .capture import CaptureSession
from .settings import setup_logging

def main():
    parser = argparse.ArgumentParser(description="Read-only R1 BLE diagnostics; no input simulation")
    parser.add_argument("--address", help="Connect to this advertised ring address")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--record", action="store_true", help="Save raw notifications to a local JSONL capture")
    parser.add_argument("--label", help="Intended action label for a recorded connection trial")
    args = parser.parse_args()
    if args.label is not None and (not args.record or not args.label.strip() or len(args.label) > 200):
        parser.error("--label requires --record and a label containing 1–200 characters")
    setup_logging()
    capture, trial_open, reason = None, False, "complete"
    def emit(kind, value):
        if capture:
            if kind == "raw_packet": capture.record_packet(value)
            elif kind in {"status", "gatt", "log", "battery", "gesture"}: capture.event(kind, value)
        line = f"{kind}: {value}"
        print(line, flush=True)
        logging.info(line)
    async def run():
        nonlocal trial_open
        transport = Transport(emit, activate_sensor=False)
        if not args.address:
            for device, name, rssi in await transport.scan():
                print(f"{name} | {device.address} | {rssi} dBm (advertisement)")
        else:
            if capture and args.label:
                capture.marker(args.label, phase="trial_start")
                trial_open = True
            try: await asyncio.wait_for(transport.run(args.address, reconnect=False), args.seconds)
            except TimeoutError: emit("status", "Diagnostic capture finished")
    try:
        if args.record:
            capture = CaptureSession(metadata={"address": args.address, "mode": "CLI"})
            print(f"Capture file: {capture.path}", flush=True)
        asyncio.run(run())
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception as exc:
        reason = "error"
        logging.exception("Diagnostics failed")
        parser.exit(1, f"Bluetooth error: {exc}\n")
    finally:
        if capture:
            try:
                if trial_open: capture.marker(args.label, phase="trial_end")
            finally:
                capture.stop(reason)

if __name__ == "__main__": main()
