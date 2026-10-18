import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from even_r1.capture import CaptureSession


def records(session):
    return [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]


def test_notification_preserves_exact_bytes_and_transport_identity(tmp_path):
    session = CaptureSession(tmp_path, {"address": "10:20:30:40:50:60"})
    packet = {"timestamp_utc": "2026-10-19T15:14:13.123456+00:00", "monotonic_ns": 123,
              "characteristic": "bae80011", "handle": 42, "length": 5,
              "hex": "0000ff0080", "connection_id": "session-1", "sequence": 8}
    session.record_packet(packet)
    assert records(session)[1] == {"type": "notification", **packet}
    assert records(session)[0]["metadata"]["address"] == "10:20:30:40:50:60"
    assert records(session)[0]["schema_version"] == 1
    assert "timestamp_utc" in records(session)[0]
    assert isinstance(records(session)[0]["monotonic_ns"], int)
    session.stop()


def test_named_trials_annotate_only_their_notifications(tmp_path):
    session = CaptureSession(tmp_path)
    session.record_packet({"hex": "00"})
    trial_id = session.marker(" одиночний дотик ", 2, "trial_start")
    session.record_packet({"hex": "01"})
    session.marker("початок руху")
    session.record_packet({"hex": "02"})
    assert session.marker("одиночний дотик", phase="trial_end") == trial_id
    session.record_packet({"hex": "03"})
    another = session.marker("одиночний дотик", 3, "trial_start")
    session.stop()
    data = records(session)
    assert "label" not in data[1] and "trial_id" not in data[1]
    for i in (2, 3, 4, 5, 6):
        assert data[i]["trial_id"] == trial_id
    assert data[3]["label"] == data[5]["label"] == "одиночний дотик"
    assert data[3]["repetition"] == data[5]["repetition"] == 2
    assert "trial_id" not in data[7] and "label" not in data[7]
    assert trial_id != another


def test_delayed_notifications_use_source_time_and_end_exclusive_boundaries(tmp_path, monkeypatch):
    now = [100]
    monkeypatch.setattr("even_r1.capture.perf_counter_ns", lambda: now[0])
    session = CaptureSession(tmp_path)
    now[0] = 200
    first = session.marker("tap", 1, "trial_start")
    session.record_packet({"monotonic_ns": 150, "hex": "before"})
    now[0] = 400
    session.marker("tap", phase="trial_end")
    now[0] = 600
    second = session.marker("swipe", 1, "trial_start")
    session.record_packet({"monotonic_ns": 300, "hex": "delayed"})
    session.record_packet({"monotonic_ns": 200, "hex": "start-boundary"})
    session.record_packet({"monotonic_ns": 400, "hex": "end-boundary"})
    session.record_packet({"monotonic_ns": 600, "hex": "next-start"})
    session.record_packet({"hex": "missing-source-time"})
    session.stop()
    data = records(session)
    packets = {record["hex"]: record for record in data if record["type"] == "notification"}
    assert "trial_id" not in packets["before"]
    assert packets["delayed"]["trial_id"] == packets["start-boundary"]["trial_id"] == first
    assert packets["delayed"]["label"] == "tap"
    assert "trial_id" not in packets["end-boundary"]
    assert packets["next-start"]["trial_id"] == packets["missing-source-time"]["trial_id"] == second
    assert [(record["phase"], record["monotonic_ns"]) for record in data if record["type"] == "marker"] == [
        ("trial_start", 200), ("trial_end", 400), ("trial_start", 600)]


def test_starting_next_trial_closes_previous_interval(tmp_path, monkeypatch):
    now = [100]
    monkeypatch.setattr("even_r1.capture.perf_counter_ns", lambda: now[0])
    session = CaptureSession(tmp_path)
    first = session.marker("tap", phase="trial_start")
    now[0] = 200
    second = session.marker("swipe", phase="trial_start")
    session.record_packet({"monotonic_ns": 150})
    session.record_packet({"monotonic_ns": 200})
    session.stop()
    packets = [record for record in records(session) if record["type"] == "notification"]
    assert [packet["trial_id"] for packet in packets] == [first, second]


def test_duplicates_flush_and_idempotent_stop(tmp_path):
    session = CaptureSession(tmp_path)
    for _ in range(3):
        assert session.record_packet({"hex": "0001"})
    assert len(records(session)) == 4  # Read while still open: every packet is flushed.
    session.stop("completed")
    session.stop("ignored")
    assert session.packet_count == 3 and not session.active
    assert session._file.closed
    assert not session.record_packet({"hex": "ff"})
    assert not session.event("status", "late")
    assert session.marker("late") is None
    assert records(session)[-1]["reason"] == "completed"
    assert records(session)[-1]["packet_count"] == 3
    assert len(records(session)) == 5


def test_unique_files_and_generic_value_serialization(tmp_path):
    first, second = CaptureSession(tmp_path), CaptureSession(tmp_path)
    assert first.path != second.path
    first.event("gatt", {"path": tmp_path, "value": "дані"})
    first.stop()
    second.stop()
    assert records(first)[1]["value"] == {"path": str(tmp_path), "value": "дані"}


def test_concurrent_notifications_remain_complete_json_lines(tmp_path):
    session = CaptureSession(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: session.record_packet({"sequence": index}), range(100)))
    session.stop()
    packets = [record for record in records(session) if record["type"] == "notification"]
    assert sorted(packet["sequence"] for packet in packets) == list(range(100))
    assert session.packet_count == records(session)[-1]["packet_count"] == 100


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_io_failure_closes_and_deactivates_session(tmp_path, operation):
    session = CaptureSession(tmp_path)
    actual_file = session._file
    broken_file = Mock(wraps=actual_file)
    getattr(broken_file, operation).side_effect = OSError("disk unavailable")
    session._file = broken_file
    with pytest.raises(OSError, match="disk unavailable"):
        session.record_packet({"hex": "ff"})
    assert actual_file.closed and not session.active
    assert session.packet_count == 0
    session.stop()


@pytest.mark.parametrize("label,repetition,phase", [
    ("", None, "marker"), (" ", None, "marker"), ("x" * 201, None, "marker"),
    ("tap", 0, "trial_start"), ("tap", True, "trial_start"), ("tap", None, "unknown"),
])
def test_invalid_markers_do_not_write_partial_record(tmp_path, label, repetition, phase):
    session = CaptureSession(tmp_path)
    with pytest.raises(ValueError):
        session.marker(label, repetition, phase)
    session.stop()
    assert [record["type"] for record in records(session)] == ["session_start", "session_end"]
