"""Passive gesture transport. Never writes application characteristic values."""
import asyncio
import logging
from bleak import BleakClient, BleakScanner
from .protocol import decode

SERVICE = "bae80001-4f05-4503-8e65-3af1f7329d1f"
NOTIFY = {f"bae800{x}-4f05-4503-8e65-3af1f7329d1f" for x in ("11", "13")}
BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"

class Transport:
    def __init__(self, emit):
        self.emit = emit
        self.stop = asyncio.Event()
        self.seen_ticks = set()
    async def scan(self, timeout=8):
        self.emit("status", "Scanning")
        try:
            async with asyncio.timeout(timeout + 15):
                found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        except TimeoutError as exc:
            raise RuntimeError("Bluetooth scan timed out. Check the adapter and try again.") from exc
        rings = []
        for device, adv in found.values():
            name = adv.local_name or device.name or ""
            if name.upper().startswith("EVEN R1") or SERVICE in [s.lower() for s in adv.service_uuids]:
                rings.append((device, name, adv.rssi))
        self.emit("log", f"Scan received {len(found)} BLE device(s); {len(rings)} matched Even R1")
        return rings
    def notification(self, sender, data):
        raw = bytes(data)
        self.emit("packet", f"{sender.uuid}  {raw.hex(' ').upper()}")
        event = decode(raw)
        if event:
            if event.tick is not None:
                key = (event.gesture, event.tick)
                if key in self.seen_ticks: return
                if len(self.seen_ticks) > 512: self.seen_ticks.clear()
                self.seen_ticks.add(key)
            self.emit("gesture", event)
    async def connect_once(self, device):
        disconnected = asyncio.Event()
        self.seen_ticks.clear()
        self.emit("status", "Connecting")
        async with BleakClient(device, disconnected_callback=lambda _: disconnected.set(), timeout=25) as client:
            count = 0
            for service in client.services:
                self.emit("gatt", f"Service {service.uuid}")
                for char in service.characteristics:
                    self.emit("gatt", f"  {char.uuid} [{', '.join(char.properties)}]")
                    if service.uuid.lower() == SERVICE and char.uuid.lower() in NOTIFY and "notify" in char.properties:
                        await client.start_notify(char, self.notification)
                        count += 1
            if not count: raise RuntimeError("No supported gesture notification characteristics found")
            self.emit("status", "Connected · listening")
            battery = client.services.get_characteristic(BATTERY)
            async def read_battery():
                if battery and "read" in battery.properties:
                    try:
                        value = await client.read_gatt_char(battery)
                        if len(value) == 1 and value[0] <= 100: self.emit("battery", value[0])
                    except Exception as exc: self.emit("log", f"Battery unavailable: {exc}")
            await read_battery()
            elapsed = 0
            while not self.stop.is_set() and not disconnected.is_set():
                await asyncio.sleep(.2)
                elapsed += .2
                if elapsed >= 60:
                    await read_battery()
                    elapsed = 0
        self.emit("battery", None)
        self.emit("status", "Disconnected")
    async def run(self, address, reconnect=True):
        delay = 1
        while not self.stop.is_set():
            try:
                rings = await self.scan()
                match = next((d for d, _, _ in rings if d.address.lower() == address.lower()), None)
                if match is None: raise RuntimeError("Saved ring not advertising; wake it and release other BLE connections")
                await self.connect_once(match)
                delay = 1
            except Exception as exc:
                logging.exception("BLE session failed")
                self.emit("status", "Connection unavailable")
                self.emit("log", str(exc))
            finally:
                self.emit("battery", None)
            if not reconnect or self.stop.is_set(): break
            self.emit("log", f"Retry in {delay}s")
            try: await asyncio.wait_for(self.stop.wait(), delay)
            except TimeoutError: pass
            delay = min(delay * 2, 30)
