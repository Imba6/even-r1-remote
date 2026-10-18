import argparse
import asyncio
import logging
from .ble import Transport
from .settings import setup_logging

def main():
    parser = argparse.ArgumentParser(description="Read-only R1 BLE diagnostics; no input simulation")
    parser.add_argument("--address", help="Connect to this advertised ring address")
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    setup_logging()
    def emit(kind, value):
        line = f"{kind}: {value}"
        print(line, flush=True)
        logging.info(line)
    async def run():
        transport = Transport(emit)
        if not args.address:
            for device, name, rssi in await transport.scan():
                print(f"{name} | {device.address} | {rssi} dBm (advertisement)")
        else:
            try: await asyncio.wait_for(transport.run(args.address, reconnect=False), args.seconds)
            except TimeoutError: emit("status", "Diagnostic capture finished")
    try: asyncio.run(run())
    except KeyboardInterrupt: pass
    except Exception as exc:
        logging.exception("Diagnostics failed")
        parser.exit(1, f"Bluetooth error: {exc}\n")

if __name__ == "__main__": main()
