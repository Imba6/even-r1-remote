from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from even_r1.ble import NOTIFY, SERVICE, Transport


@pytest.mark.parametrize("payload", [b"", b"\x00\xab\xff\x04\x01"])
def test_raw_notification_preserves_every_byte_and_timing(payload):
    events = []
    transport = Transport(lambda kind, value: events.append((kind, value)))
    sender = SimpleNamespace(uuid=sorted(NOTIFY)[0], handle=37)
    before = datetime.now(timezone.utc)

    transport.notification(sender, bytearray(payload))

    after = datetime.now(timezone.utc)
    kind, packet = events[0]
    assert kind == "raw_packet"
    assert before <= datetime.fromisoformat(packet["timestamp_utc"]) <= after
    assert datetime.fromisoformat(packet["timestamp_utc"]).utcoffset().total_seconds() == 0
    assert isinstance(packet["monotonic_ns"], int) and packet["monotonic_ns"] > 0
    assert packet["characteristic"] == sender.uuid and packet["handle"] == 37
    assert packet["length"] == len(payload)
    assert bytes.fromhex(packet["hex"]) == payload
    assert packet["hex"] == " ".join(f"{byte:02X}" for byte in payload)
    assert packet["connection_id"] is None and packet["sequence"] == 1
    assert events[1] == ("packet", f"{sender.uuid}  {packet['hex']}")


def test_unknown_notification_is_retained_without_fabricating_a_gesture():
    events = []
    transport = Transport(lambda kind, value: events.append((kind, value)))
    sender = SimpleNamespace(uuid=sorted(NOTIFY)[1])

    transport.notification(sender, bytes.fromhex("01 02 7E 99"))

    assert [kind for kind, _ in events] == ["raw_packet", "packet"]
    packet = events[0][1]
    assert packet["hex"] == "01 02 7E 99" and packet["length"] == 4
    assert packet["handle"] is None


def test_duplicate_gesture_remains_two_ordered_raw_notifications():
    events = []
    transport = Transport(lambda kind, value: events.append((kind, value)))
    sender = SimpleNamespace(uuid=sorted(NOTIFY)[0])
    payload = bytes.fromhex("00 09 61 00 01 00 00 01 00 00 00")

    transport.notification(sender, payload)
    transport.notification(sender, payload)

    packets = [value for kind, value in events if kind == "raw_packet"]
    assert len(packets) == 2
    assert [packet["sequence"] for packet in packets] == [1, 2]
    assert packets[0]["monotonic_ns"] <= packets[1]["monotonic_ns"]
    assert packets[0]["hex"] == packets[1]["hex"]
    assert sum(kind == "gesture" for kind, _ in events) == 1
    assert sum(kind == "packet" for kind, _ in events) == 2


async def test_reconnecting_starts_a_new_sequence_and_dedup_window(monkeypatch):
    events = []
    transport = Transport(lambda kind, value: events.append((kind, value)))
    sender = SimpleNamespace(uuid=sorted(NOTIFY)[0], handle=21, properties=["notify"])
    payload = bytes.fromhex("00 09 61 00 01 00 00 01 00 00 00")

    class Services(list):
        def get_characteristic(self, uuid):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            self.services = Services([SimpleNamespace(uuid=SERVICE, characteristics=[sender])])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def start_notify(self, char, callback):
            callback(char, payload)
            callback(char, payload)
            transport.stop.set()

    monkeypatch.setattr("even_r1.ble.BleakClient", Client)

    await transport.connect_once(object())
    transport.stop.clear()
    await transport.connect_once(object())

    packets = [value for kind, value in events if kind == "raw_packet"]
    assert [packet["sequence"] for packet in packets] == [1, 2, 1, 2]
    first_id, second_id = packets[0]["connection_id"], packets[2]["connection_id"]
    assert str(UUID(first_id)) == first_id and str(UUID(second_id)) == second_id
    assert first_id != second_id
    assert packets[1]["connection_id"] == first_id
    assert packets[3]["connection_id"] == second_id
    assert sum(kind == "gesture" for kind, _ in events) == 2
