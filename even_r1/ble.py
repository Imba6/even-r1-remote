"""R1 gesture receive transport with one fixed, validated touch-source request."""
import asyncio
from datetime import datetime, timezone
import logging
import sys
from time import perf_counter_ns
from uuid import uuid4
from bleak import BleakClient, BleakScanner
from .protocol import decode
from .windows_discovery import cached_ring
from .gesture_sensor import TOUCH_ENABLE_FRAME, TOUCH_ENABLE_UUID

SERVICE = "bae80001-4f05-4503-8e65-3af1f7329d1f"
NOTIFY = {f"bae800{x}-4f05-4503-8e65-3af1f7329d1f" for x in ("11", "13")}
BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
SUBSCRIPTION_TIMEOUT = 8
HEALTH_INTERVAL_NS = 2_000_000_000

class Transport:
    def __init__(self, emit, *, activate_sensor=True):
        self.emit = emit
        self.activate_sensor = activate_sensor
        self.stop = asyncio.Event()
        self.seen_ticks = set()
        self.connection_id = None
        self.sequence = 0
        self.refresh_requested = asyncio.Event()
        self._subscribed = {}
        self._connected_at_ns = None
        self._last_packet_ns = None
        self._phase = "disconnected"
        self._sensor_attempted = False
    def request_refresh(self):
        """Coalesce manual requests; call this on the transport's asyncio loop."""
        if self._connected_at_ns is not None and self._subscribed:
            self.refresh_requested.set()
    def _publish_health(self, **details):
        now = perf_counter_ns()
        self.emit("connection_health", {
            "phase": self._phase,
            "connection_id": self.connection_id,
            "subscribed_count": len(self._subscribed),
            "subscribed_channels": sorted(self._subscribed),
            "packet_count": self.sequence,
            "seconds_connected": None if self._connected_at_ns is None else max(0, now - self._connected_at_ns) / 1e9,
            "seconds_since_last_packet": None if self._last_packet_ns is None else max(0, now - self._last_packet_ns) / 1e9,
            **details,
        })
    def _publish_receive_state(self, **details):
        self._phase = "receiving" if self.sequence else "waiting"
        self.emit("status", "Connected · receiving packets" if self.sequence else "Connected · waiting for first packet")
        self._publish_health(**details)
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
        received_at_ns = perf_counter_ns()
        self._last_packet_ns = received_at_ns
        self.sequence += 1
        self.emit("raw_packet", {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "monotonic_ns": received_at_ns,
            "characteristic": str(sender.uuid),
            "handle": getattr(sender, "handle", None),
            "length": len(raw),
            "hex": raw.hex(" ").upper(),
            "connection_id": self.connection_id,
            "sequence": self.sequence,
        })
        self.emit("packet", f"{sender.uuid}  {raw.hex(' ').upper()}")
        if self._connected_at_ns is not None and self._phase == "waiting":
            self._publish_receive_state()
        event = decode(raw)
        if event:
            if event.tick is not None:
                key = (event.gesture, event.tick)
                if key in self.seen_ticks: return
                if len(self.seen_ticks) > 512: self.seen_ticks.clear()
                self.seen_ticks.add(key)
            self.emit("gesture", event)
    async def _refresh_subscriptions(self, client):
        """Rearm only established app subscriptions, using standard CCCD operations."""
        self._phase = "refreshing"
        self._publish_health()
        results = []
        for uuid, char in list(self._subscribed.items()):
            if self.stop.is_set() or not getattr(client, "is_connected", True):
                break
            try:
                await asyncio.wait_for(client.stop_notify(char), SUBSCRIPTION_TIMEOUT)
            except Exception as exc:
                # A failed CCCD disable retains the previously registered callback.
                # Do not install another callback over that same registration.
                results.append({"characteristic": uuid, "success": False, "stage": "stop", "error": str(exc) or type(exc).__name__})
                self.emit("log", f"Subscription refresh could not stop {uuid}: {exc}")
                continue
            self._subscribed.pop(uuid, None)
            if self.stop.is_set() or not getattr(client, "is_connected", True):
                results.append({"characteristic": uuid, "success": False, "stage": "start", "error": "Connection stopped"})
                break
            try:
                await asyncio.wait_for(client.start_notify(char, self.notification), SUBSCRIPTION_TIMEOUT)
            except Exception as exc:
                results.append({"characteristic": uuid, "success": False, "stage": "start", "error": str(exc) or type(exc).__name__})
                self.emit("log", f"Subscription refresh failed on {uuid}: {exc}")
            else:
                self._subscribed[uuid] = char
                results.append({"characteristic": uuid, "success": True})
                self.emit("log", f"Subscription refreshed on {uuid}")
        self._publish_receive_state(refresh_results=results)
        if not self._subscribed and not self.stop.is_set():
            raise RuntimeError("No notification subscriptions remain after refresh")
    async def _stop_subscriptions(self, client):
        for uuid, char in list(self._subscribed.items()):
            if not getattr(client, "is_connected", True):
                break
            try:
                await asyncio.wait_for(client.stop_notify(char), SUBSCRIPTION_TIMEOUT)
            except Exception as exc:
                self.emit("log", f"Notification cleanup unavailable on {uuid}: {exc}")
            else:
                self.emit("log", f"Stopped listening on {uuid}")
            self._subscribed.pop(uuid, None)
    def _publish_sensor_state(self, state, detail):
        self.emit("sensor_state", {"connection_id": self.connection_id, "state": state, "detail": detail})
        self.emit("log", detail)
    async def _enable_gesture_sensor(self, client):
        """Submit only the fixed enable request once, after both notify channels."""
        if self._sensor_attempted:
            return
        self._sensor_attempted = True
        if not self.activate_sensor:
            self._publish_sensor_state("unavailable", "Passive capture mode: touch activation is disabled")
            return
        if not NOTIFY.issubset(self._subscribed):
            self._publish_sensor_state("unavailable", "Touch enable unavailable: both ring notification channels must be subscribed")
            return
        try:
            char = client.services.get_characteristic(TOUCH_ENABLE_UUID)
            if char is None or str(char.uuid).lower() != TOUCH_ENABLE_UUID or "write-without-response" not in char.properties:
                self._publish_sensor_state("unavailable", "Touch enable unavailable: BAE80012 write-without-response characteristic is missing")
                return
            if self.stop.is_set() or not getattr(client, "is_connected", True):
                self._publish_sensor_state("unavailable", "Touch enable cancelled: connection is stopping")
                return
            self._publish_sensor_state("enabling", "Submitting the fixed ring touch-source enable request")
            await asyncio.wait_for(client.write_gatt_char(char, TOUCH_ENABLE_FRAME, response=False), SUBSCRIPTION_TIMEOUT)
        except Exception as exc:
            self._publish_sensor_state("error", f"Touch enable failed; raw packet reception remains active: {type(exc).__name__}: {exc}")
        else:
            self._publish_sensor_state("requested", "Touch enable request submitted; waiting for real ring packets")
    async def connect_once(self, device):
        disconnected = asyncio.Event()
        self.connection_id = str(uuid4())
        self.sequence = 0
        self.seen_ticks.clear()
        self._subscribed.clear()
        self.refresh_requested.clear()
        self._connected_at_ns = None
        self._last_packet_ns = None
        self._phase = "subscribing"
        self._sensor_attempted = False
        self.emit("status", "Connecting")
        self._publish_health()
        options = {"winrt": {"use_cached_services": False}} if sys.platform == "win32" else {}
        try:
            async with BleakClient(device, disconnected_callback=lambda _: disconnected.set(), timeout=25, **options) as client:
                self._connected_at_ns = perf_counter_ns()
                try:
                    for service in client.services:
                        self.emit("gatt", f"Service {service.uuid}")
                        for char in service.characteristics:
                            self.emit("gatt", f"  {char.uuid} [{', '.join(char.properties)}]")
                            if service.uuid.lower() == SERVICE and char.uuid.lower() in NOTIFY and "notify" in char.properties:
                                try:
                                    await asyncio.wait_for(client.start_notify(char, self.notification), SUBSCRIPTION_TIMEOUT)
                                except Exception as exc:
                                    self.emit("log", f"Notification unavailable on {char.uuid}: {exc}")
                                else:
                                    self._subscribed[str(char.uuid).lower()] = char
                                    self.emit("log", f"Listening on {char.uuid}")
                    if not self._subscribed: raise RuntimeError("No supported gesture notification subscriptions succeeded; see Diagnostics for details")
                    await self._enable_gesture_sensor(client)
                    self._publish_receive_state()
                    battery = client.services.get_characteristic(BATTERY)
                    async def read_battery():
                        if battery and "read" in battery.properties:
                            try:
                                value = await client.read_gatt_char(battery)
                                if len(value) == 1 and value[0] <= 100: self.emit("battery", value[0])
                            except Exception as exc: self.emit("log", f"Battery unavailable: {exc}")
                    await read_battery()
                    last_health_ns = last_battery_ns = perf_counter_ns()
                    while not self.stop.is_set() and not disconnected.is_set():
                        if self.refresh_requested.is_set():
                            self.refresh_requested.clear()
                            await self._refresh_subscriptions(client)
                        await asyncio.sleep(.2)
                        now = perf_counter_ns()
                        if now - last_health_ns >= HEALTH_INTERVAL_NS:
                            self._publish_health()
                            last_health_ns = now
                        if now - last_battery_ns >= 60_000_000_000:
                            await read_battery()
                            last_battery_ns = perf_counter_ns()
                finally:
                    await self._stop_subscriptions(client)
        finally:
            self._subscribed.clear()
            self.refresh_requested.clear()
            self._phase = "disconnected"
            self._publish_health()
            self._connected_at_ns = None
            self.emit("battery", None)
            self.emit("status", "Disconnected")
    async def run(self, address, reconnect=True, discovered_device=None):
        delay = 1
        while not self.stop.is_set():
            try:
                match = discovered_device
                discovered_device = None
                if match is None or match.address.lower() != address.lower():
                    rings = await self.scan()
                    match = next((d for d, _, _ in rings if d.address.lower() == address.lower()), None)
                    if match is None:
                        match = await cached_ring(address)
                        if match is not None:
                            self.emit("log", "Using the ring identity already known to Windows; live connection is still required")
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
