import asyncio
import json
from time import perf_counter_ns
from types import SimpleNamespace

import pytest

from even_r1 import diagnostics
from even_r1.capture import CaptureSession


def test_existing_scan_does_not_create_capture(monkeypatch, capsys):
    class Transport:
        def __init__(self, emit): self.emit = emit
        async def scan(self):
            self.emit("status", "Scanning")
            return [(SimpleNamespace(address="10:20:30:40:50:60"), "EVEN R1", -50)]
    monkeypatch.setattr(diagnostics, "Transport", Transport)
    monkeypatch.setattr(diagnostics, "setup_logging", lambda: None)
    monkeypatch.setattr(diagnostics, "CaptureSession", lambda **kwargs: pytest.fail("Unexpected capture"))
    monkeypatch.setattr("sys.argv", ["diagnostics"])
    diagnostics.main()
    output = capsys.readouterr().out
    assert "EVEN R1 | 10:20:30:40:50:60 | -50 dBm" in output
    assert "Capture file:" not in output


@pytest.mark.parametrize("arguments", [
    ["--label", "tap"], ["--record", "--label", ""],
    ["--record", "--label", " "], ["--record", "--label", "x" * 201],
])
def test_invalid_label_is_rejected_before_logging(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["diagnostics", *arguments])
    monkeypatch.setattr(diagnostics, "setup_logging", lambda: pytest.fail("Invalid arguments proceeded"))
    with pytest.raises(SystemExit) as error:
        diagnostics.main()
    assert error.value.code == 2


@pytest.mark.parametrize("outcome,reason", [
    ("complete", "complete"), ("timeout", "complete"),
    ("interrupted", "interrupted"), ("error", "error"),
])
def test_cli_capture_closes_for_every_run_outcome(tmp_path, monkeypatch, capsys, outcome, reason):
    sessions = []
    def create_capture(**kwargs):
        session = CaptureSession(tmp_path, **kwargs)
        sessions.append(session)
        return session
    packet = {"timestamp_utc": "2026-10-19T12:00:00+00:00", "characteristic": "bae80011",
              "handle": 23, "length": 3, "hex": "00ff00", "connection_id": "connection-1", "sequence": 1}
    class Transport:
        def __init__(self, emit): self.emit = emit
        async def run(self, address, reconnect):
            assert address == "10:20:30:40:50:60" and reconnect is False
            self.emit("status", "Connected")
            self.emit("gatt", "Service bae80001")
            packet["monotonic_ns"] = perf_counter_ns()
            self.emit("raw_packet", packet)
            self.emit("gesture", {"gesture": "tap"})
            self.emit("battery", 80)
            if outcome == "timeout": await asyncio.Event().wait()
            if outcome == "interrupted": raise KeyboardInterrupt()
            if outcome == "error": raise RuntimeError("adapter unavailable")
    monkeypatch.setattr(diagnostics, "Transport", Transport)
    monkeypatch.setattr(diagnostics, "CaptureSession", create_capture)
    monkeypatch.setattr(diagnostics, "setup_logging", lambda: None)
    monkeypatch.setattr("sys.argv", ["diagnostics", "--record", "--label", "tap", "--address",
                                     "10:20:30:40:50:60", "--seconds", "0.02"])
    if outcome == "error":
        with pytest.raises(SystemExit) as error:
            diagnostics.main()
        assert error.value.code == 1
    else:
        diagnostics.main()
    session = sessions[0]
    assert not session.active and session._file.closed
    data = [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]
    assert data[0]["metadata"] == {"address": "10:20:30:40:50:60", "mode": "CLI"}
    saved_packet = next(record for record in data if record["type"] == "notification")
    assert {key: saved_packet[key] for key in packet} == packet
    assert saved_packet["label"] == "tap"
    assert [record["phase"] for record in data if record["type"] == "marker"] == ["trial_start", "trial_end"]
    assert {record["kind"] for record in data if record["type"] == "event"} >= {"status", "gatt", "gesture", "battery"}
    assert data[-1]["type"] == "session_end" and data[-1]["reason"] == reason
    assert data[-1]["packet_count"] == 1
    assert f"Capture file: {session.path}" in capsys.readouterr().out


def test_capture_stops_even_when_final_marker_fails(tmp_path, monkeypatch):
    session = CaptureSession(tmp_path)
    original_marker = session.marker
    def marker(label, repetition=None, phase="marker"):
        if phase == "trial_end": raise OSError("marker failure")
        return original_marker(label, repetition, phase)
    class Transport:
        def __init__(self, emit): pass
        async def run(self, address, reconnect): pass
    monkeypatch.setattr(session, "marker", marker)
    monkeypatch.setattr(diagnostics, "CaptureSession", lambda **kwargs: session)
    monkeypatch.setattr(diagnostics, "setup_logging", lambda: None)
    monkeypatch.setattr(diagnostics, "Transport", Transport)
    monkeypatch.setattr("sys.argv", ["diagnostics", "--record", "--label", "tap", "--address", "address"])
    with pytest.raises(OSError, match="marker failure"):
        diagnostics.main()
    assert not session.active and session._file.closed
