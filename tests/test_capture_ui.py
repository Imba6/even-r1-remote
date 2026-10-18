"""Exercise capture timing and input isolation through real Qt widgets.

Notification payloads in this module are synthetic test inputs; no BLE or
operating system input controllers are created.
"""
import json
from datetime import datetime, timezone
from time import perf_counter_ns
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from even_r1 import ui
from even_r1.capture_ui import CapturePanel
from even_r1.settings import Settings


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app, tmp_path):
    widget = CapturePanel(lambda: {"source": "synthetic UI test"}, tmp_path)
    yield widget
    widget.timer.stop()
    if widget.recording:
        widget.stop_recording("test cleanup")
    widget.close()


def records(panel):
    return [json.loads(line) for line in panel.last_path.read_text(encoding="utf-8").splitlines()]


def packet(sequence=1):
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "monotonic_ns": perf_counter_ns(),
        "characteristic": "bae80011-4f05-4503-8e65-3af1f7329d1f",
        "handle": 21,
        "length": 4,
        "hex": "01 02 7E 99",
        "connection_id": "synthetic-test-connection",
        "sequence": sequence,
    }


def begin_series(panel, repeats=2):
    panel.feed("status", "Connected · listening")
    panel.start_button.click()
    panel.action_label.setCurrentText("Single tap")
    panel.repeats.setValue(repeats)
    panel.series_button.click()
    panel.timer.stop()  # Advance the real state machine without wall-clock waits.


def advance(panel, phase, seconds):
    assert (panel.phase, panel.remaining) == (phase, seconds)
    for _ in range(seconds):
        panel.tick()


def test_guided_series_saves_each_phase_and_keeps_recording(panel):
    begin_series(panel, repeats=2)
    panel.feed("raw_packet", packet(1))
    advance(panel, "baseline", 5)
    for repetition in (1, 2):
        panel.feed("raw_packet", packet(repetition * 3 - 1))
        advance(panel, "prepare", 3)
        panel.feed("raw_packet", packet(repetition * 3))
        advance(panel, "action", 5)
        panel.feed("raw_packet", packet(repetition * 3 + 1))
        advance(panel, "rest", 3)

    assert panel.phase == "idle" and not panel.timer.isActive()
    assert panel.recording and panel.series_button.isEnabled()
    assert not panel.cancel_button.isEnabled()
    panel.feed("raw_packet", packet(8))
    data = records(panel)
    notifications = [row for row in data if row["type"] == "notification"]
    assert panel.session.packet_count == len(notifications) == 8
    assert panel.count_label.text() == "8 packets recorded"
    assert [row.get("label") for row in notifications] == [
        "Rest / no action", None, "Single tap", "Rest / no action",
        None, "Single tap", "Rest / no action", None,
    ]
    actions = [row for row in notifications if row.get("label") == "Single tap"]
    assert [row["repetition"] for row in actions] == [1, 2]
    assert len({row["trial_id"] for row in actions}) == 2
    assert all(row["hex"] == "01 02 7E 99" and row["length"] == 4 for row in notifications)
    assert data[0]["metadata"] == {"source": "synthetic UI test"}
    assert any(row.get("kind") == "series_complete" for row in data)
    assert not any(row["type"] == "session_end" for row in data)

    panel.stop_button.click()
    assert not panel.recording and panel.start_button.isEnabled()
    end = records(panel)[-1]
    assert (end["type"], end["packet_count"], end["reason"]) == ("session_end", 8, "user")


def test_delayed_notification_keeps_source_action_context(panel):
    begin_series(panel, repeats=1)
    advance(panel, "baseline", 5)
    advance(panel, "prepare", 3)
    queued = packet()
    advance(panel, "action", 5)
    assert panel.phase == "rest"

    # A queued Qt delivery can arrive after a phase change; the BLE source
    # timestamp must still attach the packet to its original action window.
    panel.feed("raw_packet", queued)
    stored = [row for row in records(panel) if row["type"] == "notification"][0]
    assert stored["label"] == "Single tap" and stored["repetition"] == 1
    assert stored["monotonic_ns"] == queued["monotonic_ns"]


def test_disconnect_cancels_series_and_preserves_open_recording(panel):
    begin_series(panel, repeats=3)
    advance(panel, "baseline", 5)
    advance(panel, "prepare", 3)
    panel.feed("raw_packet", packet())
    panel.feed("status", "Disconnected")

    assert panel.phase == "idle" and not panel.timer.isActive()
    assert not panel.connected and not panel.series_button.isEnabled()
    assert panel.recording and panel.stop_button.isEnabled()
    panel.feed("raw_packet", packet(2))
    data = records(panel)
    cancelled = [row for row in data if row.get("kind") == "series_cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0]["value"] == {
        "reason": "connection lost", "label": "Single tap", "repetition": 1, "phase": "action",
    }
    assert [row.get("label") for row in data if row["type"] == "notification"] == ["Single tap", None]
    assert not any(row["type"] == "session_end" for row in data)

    panel.stop_button.click()
    assert records(panel)[-1]["type"] == "session_end"
    assert records(panel)[-1]["packet_count"] == 2


def test_stop_during_series_closes_trial_and_ends_file(panel):
    begin_series(panel, repeats=2)
    panel.feed("raw_packet", packet())
    panel.stop_button.click()
    original = panel.last_path.read_bytes()
    panel.tick()
    panel.feed("raw_packet", packet(2))

    assert panel.phase == "idle" and not panel.timer.isActive()
    assert not panel.recording and not panel.stop_button.isEnabled()
    assert panel.last_path.read_bytes() == original
    data = records(panel)
    assert data[-1]["type"] == "session_end" and data[-1]["packet_count"] == 1
    assert any(row.get("kind") == "series_cancelled" and row["value"]["reason"] == "user" for row in data)
    markers = [row for row in data if row["type"] == "marker"]
    assert [row["phase"] for row in markers] == ["trial_start", "trial_end"]
    assert markers[0]["trial_id"] == markers[1]["trial_id"]


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    class IsolatedActions:
        def __init__(self, settings):
            self.enabled = False
            self.last = {}
            self.execute = Mock(return_value="Paused")

    monkeypatch.setattr(ui, "Settings", lambda: Settings(tmp_path / "settings.json"))
    monkeypatch.setattr(ui, "Actions", IsolatedActions)
    widget = ui.Window()
    widget.capture_panel.directory = tmp_path / "captures"
    yield widget
    widget.capture_panel.timer.stop()
    if widget.capture_panel.recording:
        widget.capture_panel.stop_recording("test cleanup")
    widget.worker = None  # This fixture only uses inert worker stubs.
    widget.quitting = True
    widget.tray.hide()
    widget.close()


def test_recording_pauses_windows_controls_until_explicit_stop(window):
    window.enable.setChecked(True)
    assert window.actions.enabled
    panel = window.capture_panel
    begin_series(panel, repeats=1)
    assert not window.actions.enabled and not window.enable.isChecked()
    assert not window.enable.isEnabled()
    advance(panel, "baseline", 5)
    advance(panel, "prepare", 3)
    advance(panel, "action", 5)
    advance(panel, "rest", 3)

    assert panel.recording and not window.enable.isEnabled()
    panel.stop_button.click()
    assert window.enable.isEnabled() and not window.enable.isChecked()
    assert not window.actions.enabled
    window.enable.setChecked(True)
    assert window.actions.enabled


def test_raw_packets_do_not_dispatch_windows_actions(window):
    panel = window.capture_panel
    panel.start_button.click()
    raw = {**packet(), "length": 3, "hex": "FF 04 01"}
    window.on_transport_event("raw_packet", raw)
    window.on_transport_event("packet", f"{raw['characteristic']}  {raw['hex']}")

    window.actions.execute.assert_not_called()
    assert panel.session.packet_count == 1
    assert "FF 04 01" in panel.packets.toPlainText()
    assert window.last.text() == "Waiting for a real ring gesture"


def test_disk_error_is_visible_and_releases_controls(window, monkeypatch):
    warnings = []
    monkeypatch.setattr("even_r1.capture_ui.QMessageBox.warning", lambda *args: warnings.append(args[1:]))
    panel = window.capture_panel
    begin_series(panel)
    monkeypatch.setattr(panel.session, "record_packet", Mock(side_effect=OSError("Test disk full")))

    window.on_transport_event("raw_packet", packet())

    assert warnings == [("Recording failed", "Test disk full")]
    assert "Test disk full" in panel.instruction.text()
    assert not panel.recording and panel.phase == "idle" and not panel.timer.isActive()
    assert window.enable.isEnabled() and not window.actions.enabled
    assert panel.start_button.isEnabled() and not panel.stop_button.isEnabled()


def test_final_window_close_ends_capture_without_a_bluetooth_worker(window):
    window.settings.data["minimize_tray"] = False
    panel = window.capture_panel
    panel.start_button.click()
    panel.feed("raw_packet", packet())
    assert window.worker is None and panel.recording

    window.close()

    assert not panel.recording
    end = records(panel)[-1]
    assert (end["type"], end["reason"], end["packet_count"]) == ("session_end", "window close", 1)


def test_disconnect_button_cancels_series_before_worker_finishes(window):
    class PendingWorker:
        address = "synthetic-test-address"
        stop = Mock()

        def isRunning(self):
            return True

    window.worker = PendingWorker()
    panel = window.capture_panel
    begin_series(panel)
    assert panel.phase == "baseline"

    window.disconnect_button.click()

    window.worker.stop.assert_called_once_with()
    assert window.status.text() == "Disconnecting"
    assert not panel.connected and panel.phase == "idle"
    assert panel.recording and not panel.series_button.isEnabled()
    assert not panel.timer.isActive()
    cancelled = [row for row in records(panel) if row.get("kind") == "series_cancelled"]
    assert len(cancelled) == 1 and cancelled[0]["value"]["reason"] == "connection lost"
    window.worker = None
