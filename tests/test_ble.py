"""Receive lifecycle tests with real transport control flow and an inert GATT peer."""
from collections import Counter
from types import SimpleNamespace

import pytest

from even_r1 import ble
from even_r1.ble import NOTIFY, SERVICE, Transport
from even_r1.gesture_sensor import TOUCH_ENABLE_FRAME, TOUCH_ENABLE_UUID


@pytest.fixture
def peer(monkeypatch):
    state = SimpleNamespace(calls=[], options=None, starts=Counter(), stop_fail=set(),
                            start_fail=set(), closed=False, connected=True, writes=[],
                            has_write_characteristic=True, write_error=None, write_callback=None)
    chars = [SimpleNamespace(uuid=uuid, properties=["notify"], handle=index)
             for index, uuid in enumerate(sorted(NOTIFY), 1)]
    state.chars = chars
    state.write_char = SimpleNamespace(uuid=TOUCH_ENABLE_UUID, properties=["write-without-response"], handle=3)
    dfu = SimpleNamespace(uuid="8ec90003-f315-4f60-9fb8-838830daea50", properties=["notify", "write"])

    class Services(list):
        def get_characteristic(self, uuid):
            return state.write_char if uuid == TOUCH_ENABLE_UUID and state.has_write_characteristic else None

    class Client:
        def __init__(self, device, **options):
            state.options = options
            self.services = Services([SimpleNamespace(uuid=SERVICE, characteristics=[*chars, state.write_char]),
                                      SimpleNamespace(uuid="0000fe59-0000-1000-8000-00805f9b34fb", characteristics=[dfu])])

        @property
        def is_connected(self):
            return state.connected

        async def __aenter__(self):
            state.closed = False
            return self

        async def __aexit__(self, *args):
            state.calls.append(("close", None))
            state.closed = True

        async def start_notify(self, char, callback):
            state.calls.append(("start", char.uuid))
            state.starts[char.uuid] += 1
            if (char.uuid, state.starts[char.uuid]) in state.start_fail:
                raise OSError("subscription denied")

        async def stop_notify(self, char):
            assert not state.closed
            state.calls.append(("stop", char.uuid))
            if char.uuid in state.stop_fail:
                raise OSError("disable denied")

        async def write_gatt_char(self, char, data, *, response):
            # Every permitted write must be this exact, narrow request; no DFU,
            # health, auth, arbitrary bytes, or cleanup disable is accepted.
            assert char is state.write_char and char.uuid == TOUCH_ENABLE_UUID
            assert data == TOUCH_ENABLE_FRAME and response is False
            state.writes.append((char.uuid, bytes(data), response, list(state.calls)))
            if state.write_error:
                raise state.write_error
            if state.write_callback:
                state.write_callback()

        async def pair(self, *args, **kwargs):
            raise AssertionError("No pairing changes")

    monkeypatch.setattr(ble, "BleakClient", Client)
    return state


@pytest.mark.parametrize("platform", ["win32", "linux"])
async def test_fresh_services_and_explicit_cleanup_before_closing(peer, monkeypatch, platform):
    monkeypatch.setattr(ble.sys, "platform", platform)
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())

    uuids = sorted(NOTIFY)
    assert peer.calls == [("start", uuid) for uuid in uuids] + [("stop", uuid) for uuid in uuids] + [("close", None)]
    assert peer.options.get("winrt") == ({"use_cached_services": False} if platform == "win32" else None)
    waiting = next(value for kind, value in events if kind == "connection_health" and value["phase"] == "waiting")
    assert waiting["subscribed_count"] == 2 and waiting["packet_count"] == 0
    assert waiting["seconds_since_last_packet"] is None
    assert waiting["seconds_connected"] >= 0
    assert not any(kind == "status" and "receiving" in value for kind, value in events)
    assert events[-1] == ("status", "Disconnected")
    assert next(value for kind, value in reversed(events) if kind == "connection_health")["subscribed_count"] == 0


async def test_first_real_packet_changes_receive_state_without_decoding(peer):
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.notification(peer.chars[0], bytes.fromhex("00 1A 89 01 01 00 00"))
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())

    assert ("status", "Connected · receiving packets") in events
    raw_index = next(index for index, (kind, _) in enumerate(events) if kind == "raw_packet")
    receiving_index = events.index(("status", "Connected · receiving packets"))
    assert raw_index < receiving_index
    health = next(value for kind, value in events if kind == "connection_health" and value["phase"] == "receiving")
    assert health["packet_count"] == 1 and health["seconds_since_last_packet"] >= 0
    assert not any(kind == "gesture" for kind, _ in events)


async def test_manual_refresh_coalesces_and_rearms_both_channels(peer, monkeypatch):
    events = []
    timeouts = []
    real_wait = ble.asyncio.wait_for

    async def bounded(awaitable, timeout):
        timeouts.append(timeout)
        return await real_wait(awaitable, timeout)

    monkeypatch.setattr(ble.asyncio, "wait_for", bounded)

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.request_refresh()
            transport.request_refresh()
        if kind == "connection_health" and "refresh_results" in value:
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())

    first, second = sorted(NOTIFY)
    assert peer.calls == [("start", first), ("start", second), ("stop", first), ("start", first),
                          ("stop", second), ("start", second), ("stop", first), ("stop", second), ("close", None)]
    refreshed = [value for kind, value in events if kind == "connection_health" and "refresh_results" in value]
    assert len(refreshed) == 1
    assert refreshed[0]["subscribed_count"] == 2
    assert all(result["success"] for result in refreshed[0]["refresh_results"])
    assert all(timeout == ble.SUBSCRIPTION_TIMEOUT for timeout in timeouts)
    assert not transport.refresh_requested.is_set()
    assert len(peer.writes) == 1  # CCCD refresh never resends the touch command.


async def test_refresh_failure_counts_only_remaining_subscription(peer):
    first, second = sorted(NOTIFY)
    peer.start_fail.add((second, 2))
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.request_refresh()
        if kind == "connection_health" and "refresh_results" in value:
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())

    health = next(value for kind, value in events if kind == "connection_health" and "refresh_results" in value)
    assert health["subscribed_count"] == 1 and health["subscribed_channels"] == [first]
    failed = next(result for result in health["refresh_results"] if not result["success"])
    assert failed["characteristic"] == second and failed["stage"] == "start"
    assert "subscription denied" in failed["error"]
    assert peer.calls[-2:] == [("stop", first), ("close", None)]


async def test_packet_during_refresh_is_retained_and_status_becomes_receiving(peer):
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.request_refresh()
        if kind == "log" and value.startswith("Subscription refreshed") and not transport.sequence:
            transport.notification(peer.chars[0], b"\xab\xcd")
        if kind == "connection_health" and "refresh_results" in value:
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    assert ("status", "Connected · receiving packets") in events
    assert [value["hex"] for kind, value in events if kind == "raw_packet"] == ["AB CD"]
    health = next(value for kind, value in events if kind == "connection_health" and "refresh_results" in value)
    assert health["phase"] == "receiving" and health["packet_count"] == 1


async def test_failed_disable_does_not_overwrite_existing_handler(peer):
    first, second = sorted(NOTIFY)
    peer.stop_fail.add(first)
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.request_refresh()
        if kind == "connection_health" and "refresh_results" in value:
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())

    assert peer.starts[first] == 1 and peer.starts[second] == 2
    health = next(value for kind, value in events if kind == "connection_health" and "refresh_results" in value)
    assert health["subscribed_count"] == 2
    assert health["refresh_results"][0]["stage"] == "stop"
    assert not health["refresh_results"][0]["success"]
    assert peer.closed


async def test_all_refresh_failures_close_and_report_no_subscriptions(peer):
    peer.start_fail.update((uuid, 2) for uuid in NOTIFY)
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.request_refresh()

    transport = Transport(emit)
    with pytest.raises(RuntimeError, match="No notification subscriptions remain"):
        await transport.connect_once(object())

    assert peer.closed
    health = [value for kind, value in events if kind == "connection_health"]
    assert health[-1]["phase"] == "disconnected" and health[-1]["subscribed_count"] == 0
    assert health[-2]["subscribed_count"] == 0


async def test_disconnected_peer_skips_cleanup_cccd_writes(peer):
    def emit(kind, value):
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            peer.connected = False
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    assert not any(operation == "stop" for operation, _ in peer.calls)
    assert peer.closed


async def test_heartbeat_ages_use_elapsed_clock_and_reset_for_new_connection(peer, monkeypatch):
    clock = SimpleNamespace(now=10_000_000_000)
    monkeypatch.setattr(ble, "perf_counter_ns", lambda: clock.now)
    events = []

    async def advance(_):
        clock.now += 2_500_000_000

    monkeypatch.setattr(ble.asyncio, "sleep", advance)

    def emit(kind, value):
        events.append((kind, value))
        if kind != "connection_health":
            return
        if value["phase"] == "waiting" and value["seconds_connected"] == 2.5:
            transport.notification(peer.chars[0], b"\xab")
        if value["phase"] == "receiving" and value["seconds_since_last_packet"] == 2.5:
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    health = [value for kind, value in events if kind == "connection_health"]
    assert any(value["phase"] == "receiving" and value["seconds_connected"] == 5 and
               value["seconds_since_last_packet"] == 2.5 and value["packet_count"] == 1 for value in health)
    old_id = transport.connection_id
    transport.stop.clear()
    await transport.connect_once(object())
    assert transport.connection_id != old_id
    new_health = [value for kind, value in events if kind == "connection_health" and value["connection_id"] == transport.connection_id]
    assert new_health[0]["packet_count"] == 0 and new_health[0]["seconds_since_last_packet"] is None
    assert new_health[0]["seconds_connected"] is None
    assert len(peer.writes) == 2  # A real replacement connection needs one request.


async def test_touch_enable_sent_once_after_both_subscriptions_without_claiming_rx(peer):
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    assert len(peer.writes) == 1
    uuid, frame, response, before_write = peer.writes[0]
    assert uuid == TOUCH_ENABLE_UUID and frame == TOUCH_ENABLE_FRAME and response is False
    assert before_write == [("start", channel) for channel in sorted(NOTIFY)]
    sensor = [value for kind, value in events if kind == "sensor_state"]
    assert [value["state"] for value in sensor] == ["enabling", "requested"]
    assert all(value["connection_id"] == transport.connection_id for value in sensor)
    assert not any(kind == "raw_packet" for kind, _ in events)
    assert not any(kind == "status" and "receiving" in value for kind, value in events)


@pytest.mark.parametrize("failure", [OSError("write denied"), TimeoutError("write timed out")])
async def test_touch_enable_failure_retains_live_raw_channel(peer, failure):
    peer.write_error = failure
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.notification(peer.chars[0], bytes.fromhex("00 09 61 00 01 00 00 01 00 00 00"))
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    assert len(peer.writes) == 1
    failed = next(value for kind, value in events if kind == "sensor_state" and value["state"] == "error")
    assert str(failure) in failed["detail"]
    assert any(kind == "raw_packet" for kind, _ in events)
    assert any(kind == "gesture" for kind, _ in events)
    assert ("status", "Connected · receiving packets") in events


@pytest.mark.parametrize("reason", ["missing", "wrong_properties", "wrong_uuid", "one_channel"])
async def test_touch_enable_unavailable_never_writes_or_blocks_existing_notifications(peer, reason):
    if reason == "missing":
        peer.has_write_characteristic = False
    elif reason == "wrong_properties":
        peer.write_char.properties = ["write"]
    elif reason == "wrong_uuid":
        peer.write_char.uuid = "8ec90003-f315-4f60-9fb8-838830daea50"
    else:
        peer.start_fail.add((sorted(NOTIFY)[1], 1))
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.notification(peer.chars[0], b"\xab")
            transport.stop.set()

    transport = Transport(emit)
    await transport.connect_once(object())
    assert not peer.writes
    assert any(kind == "sensor_state" and value["state"] == "unavailable" for kind, value in events)
    assert any(kind == "raw_packet" for kind, _ in events)


async def test_immediate_gesture_during_enable_write_is_preserved(peer):
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if kind == "status" and value == "Connected · receiving packets":
            transport.stop.set()

    transport = Transport(emit)
    peer.write_callback = lambda: transport.notification(peer.chars[0], bytes.fromhex("00 09 61 00 04 00 00 01 00 00 00"))
    await transport.connect_once(object())
    assert len(peer.writes) == 1
    assert any(kind == "raw_packet" and value["hex"].startswith("00 09 61 00 04") for kind, value in events)
    assert ("status", "Connected · receiving packets") in events
    assert ("status", "Connected · waiting for first packet") not in events


async def test_passive_transport_option_never_activates_sensor(peer):
    events = []

    def emit(kind, value):
        events.append((kind, value))
        if (kind, value) == ("status", "Connected · waiting for first packet"):
            transport.notification(peer.chars[0], b"\xab")
            transport.stop.set()

    transport = Transport(emit, activate_sensor=False)
    await transport.connect_once(object())
    assert not peer.writes
    assert len([operation for operation, _ in peer.calls if operation == "start"]) == 2
    assert any(kind == "raw_packet" for kind, _ in events)
    assert any(kind == "sensor_state" and "Passive capture mode" in value["detail"] for kind, value in events)
