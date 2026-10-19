"""Exercise the complete packet history with real Qt widgets and mock BLE data.

No Bluetooth connection or Windows input controller is created. Notifications
pass through the same raw-packet event path as a connected ring.
"""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from even_r1.ble import NOTIFY, Transport
from even_r1.capture_ui import CapturePanel
from even_r1.capture import CaptureSession
from even_r1.packet_viewer import LivePacketViewer
from even_r1.settings import Settings
from even_r1 import ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app):
    widget = LivePacketViewer()
    widget.resize(780, 420)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def notification_source(receive):
    """Emit raw events from actual notification parsing, without a BLE client."""
    captured = []

    def publish(kind, value):
        if kind == "raw_packet":
            captured.append(value)
            receive(value)

    transport = Transport(publish)
    channels = [SimpleNamespace(uuid=uuid, handle=21 + index)
                for index, uuid in enumerate(sorted(NOTIFY))]
    return transport, channels, captured


def fill_history(transport, channels, amount=160):
    for index in range(amount):
        # Deliberately unknown to the gesture decoder; each payload is unique.
        payload = b"\xF5\x00" + index.to_bytes(2, "little") + b"\xEF"
        transport.notification(channels[index % len(channels)], payload)


def test_all_raw_notifications_remain_visible_past_previous_100_line_limit(viewer):
    transport, channels, captured = notification_source(viewer.append_packet)
    fill_history(transport, channels)
    duplicate = bytes.fromhex("DE AD BE EF 7E 99")
    for _ in range(3):
        transport.notification(channels[0], duplicate)

    text = viewer.packets.toPlainText()
    assert viewer.packets.isReadOnly()
    assert viewer.packets.document().maximumBlockCount() == 0
    assert viewer.received_count == len(captured) == 163
    assert "163" in viewer.count_label.text()
    assert {packet["characteristic"] for packet in captured} == NOTIFY
    for packet in captured:
        assert packet["timestamp_utc"] in text
        assert packet["characteristic"] in text
        assert packet["hex"] in text
    assert text.count("DE AD BE EF 7E 99") == 3
    assert text.index(captured[0]["hex"]) < text.index(captured[159]["hex"])


def test_live_display_continues_before_during_and_after_file_recording(viewer):
    transport, channels, captured = notification_source(viewer.append_packet)
    viewer.set_recording(False)
    assert "off" in viewer.recording_label.text().lower()
    transport.notification(channels[0], bytes.fromhex("F5 10 00 EF"))

    viewer.set_recording(True)
    assert "on" in viewer.recording_label.text().lower()
    transport.notification(channels[1], bytes.fromhex("F5 20 00 EF"))

    viewer.set_recording(False)
    assert "off" in viewer.recording_label.text().lower()
    transport.notification(channels[0], bytes.fromhex("F5 30 00 EF"))

    assert viewer.received_count == 3
    text = viewer.packets.toPlainText()
    assert all(packet["hex"] in text for packet in captured)


def test_paused_auto_scroll_keeps_reading_position_while_retaining_new_data(viewer, app):
    transport, channels, captured = notification_source(viewer.append_packet)
    assert viewer.auto_scroll.isChecked()
    fill_history(transport, channels)
    app.processEvents()
    scrollbar = viewer.packets.verticalScrollBar()
    assert scrollbar.maximum() > 0
    assert scrollbar.value() == scrollbar.maximum()

    viewer.auto_scroll.setChecked(False)
    scrollbar.setValue(0)
    app.processEvents()
    transport.notification(channels[1], bytes.fromhex("F5 AA BB CC DD EF"))
    app.processEvents()

    assert scrollbar.value() == 0
    assert captured[0]["hex"] in viewer.packets.toPlainText()
    assert captured[-1]["hex"] in viewer.packets.toPlainText()
    assert viewer.received_count == 161

    viewer.auto_scroll.setChecked(True)
    transport.notification(channels[0], bytes.fromhex("F5 EE DD CC BB EF"))
    app.processEvents()
    assert scrollbar.value() == scrollbar.maximum()


def test_search_wraps_through_duplicates_without_filtering_the_history(viewer):
    transport, channels, _ = notification_source(viewer.append_packet)
    fill_history(transport, channels, amount=130)
    query = "DE AD 7E 99"
    transport.notification(channels[0], bytes.fromhex(query))
    transport.notification(channels[1], bytes.fromhex("F5 50 40 EF"))
    transport.notification(channels[1], bytes.fromhex(query))
    original = viewer.packets.toPlainText()

    viewer.auto_scroll.setChecked(False)
    viewer.search.setText(query)
    cursor = viewer.packets.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    viewer.packets.setTextCursor(cursor)
    viewer.find_next()
    first = viewer.packets.textCursor()
    assert first.selectedText() == query
    viewer.find_next()
    second = viewer.packets.textCursor()
    assert second.selectedText() == query
    assert first.selectionStart() < second.selectionStart()
    viewer.find_next()
    assert viewer.packets.textCursor().selectionStart() == first.selectionStart()
    assert viewer.packets.toPlainText() == original
    assert viewer.received_count == 133

    viewer.search.setText("no such packet")
    viewer.find_next()
    assert viewer.packets.toPlainText() == original
    assert viewer.received_count == 133


def test_capture_panel_also_retains_every_packet_with_file_recording_off(app, tmp_path):
    panel = CapturePanel(directory=tmp_path)
    try:
        transport, channels, captured = notification_source(
            lambda packet: panel.feed("raw_packet", packet))
        fill_history(transport, channels)

        assert not panel.recording
        assert panel.packets.document().maximumBlockCount() == 0
        text = panel.packets.toPlainText()
        assert all(packet["hex"] in text for packet in captured)
        assert captured[0]["timestamp_utc"] in text
        assert captured[-1]["timestamp_utc"] in text
        assert not list(tmp_path.iterdir())
    finally:
        panel.timer.stop()
        panel.close()


def test_saved_capture_import_keeps_duplicates_and_live_history_then_exports_all(viewer, tmp_path, monkeypatch):
    transport, channels, captured = notification_source(lambda packet: None)
    fill_history(transport, channels, amount=130)
    duplicate = bytes.fromhex("DE AD BE EF 99")
    for _ in range(2):
        transport.notification(channels[1], duplicate)
    session = CaptureSession(tmp_path)
    session.marker("Single tap", 1)
    for packet in captured:
        session.record_packet(packet)
    session.event("status", "Connected · listening")
    session.stop()

    live_transport, live_channels, live = notification_source(viewer.append_packet)
    live_transport.notification(live_channels[0], bytes.fromhex("F5 AA 55 EF"))
    assert viewer.load_capture(session.path) == 132
    live_transport.notification(live_channels[1], bytes.fromhex("F5 BB 66 EF"))

    text = viewer.packets.toPlainText()
    assert viewer.received_count == 134
    assert "134" in viewer.count_label.text()
    assert text.count("FILE") == 132
    assert text.count("RX") == 2
    assert text.count("DE AD BE EF 99") == 2
    assert all(packet["hex"] in text for packet in captured + live)
    assert "Single tap" not in text
    assert "Connected · listening" not in text
    assert text.index(live[0]["hex"]) < text.index(captured[0]["hex"])
    assert text.index(captured[-1]["hex"]) < text.index(live[-1]["hex"])

    destination = tmp_path / "all-displayed-packets.txt"
    monkeypatch.setattr("even_r1.packet_viewer.QFileDialog.getSaveFileName",
                        lambda *args: (str(destination), "Text (*.txt)"))
    viewer.export_view()
    assert destination.read_text(encoding="utf-8") == text


def health(phase="waiting", connection_id="connection-a", packet_count=0, age=None):
    return {"phase": phase, "connection_id": connection_id, "subscribed_count": 2,
            "subscribed_channels": sorted(NOTIFY), "packet_count": packet_count,
            "seconds_since_last_packet": age, "seconds_connected": 8.0}


def test_imported_history_never_implies_current_connection_is_receiving(viewer, tmp_path):
    transport, channels, captured = notification_source(lambda packet: None)
    fill_history(transport, channels, amount=3)
    path = tmp_path / "old.jsonl"
    path.write_text("\n".join(json.dumps({"type": "notification", **row}) for row in captured), encoding="utf-8")
    viewer.set_connection_health(health())
    viewer.load_capture(path)

    assert viewer.received_count == viewer.imported_count == 3
    assert viewer.live_count == viewer.connection_packet_count == 0
    assert "0 live RX" in viewer.count_label.text()
    assert "3 imported FILE" in viewer.count_label.text()
    assert "waiting for first packet" in viewer.health_label.text()
    assert "0 live RX in current connection" in viewer.health_label.text()

    viewer.append_packet(captured[0])
    viewer.set_connection_health(health("receiving", packet_count=1, age=1.5))
    assert viewer.live_count == viewer.connection_packet_count == 1
    assert viewer.imported_count == 3
    assert "last RX 1.5 s ago" in viewer.health_label.text()
    assert "1 live RX in current connection" in viewer.health_label.text()

    viewer.set_connection_health(health("disconnected", packet_count=1, age=2))
    assert "Disconnected" in viewer.health_label.text()
    assert not viewer.refresh_button.isEnabled()
    viewer.set_connection_health(health("subscribing", connection_id="connection-b"))
    assert viewer.connection_packet_count == 0
    assert viewer.live_count == 1
    assert not viewer.refresh_button.isEnabled()
    viewer.set_connection_health(health(connection_id="connection-b"))
    assert "waiting for first packet" in viewer.health_label.text()
    assert viewer.refresh_button.isEnabled()
    viewer.set_connection_health(health("refreshing", connection_id="connection-b"))
    assert "Refreshing" in viewer.health_label.text()
    assert not viewer.refresh_button.isEnabled()


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
    widget.worker = None
    widget.quitting = True
    widget.tray.hide()
    widget.close()


def test_window_displays_raw_events_once_independent_of_file_recording(window):
    transport = Transport(window.on_transport_event)
    channels = [SimpleNamespace(uuid=uuid) for uuid in sorted(NOTIFY)]
    viewer = window.packet_viewer
    panel = window.capture_panel
    assert window.tabs.tabText(window.tabs.indexOf(viewer)) == "All packets"
    assert "off" in viewer.recording_label.text().lower()

    transport.notification(channels[0], bytes.fromhex("F5 11 00 EF"))
    panel.start_button.click()
    assert "on" in viewer.recording_label.text().lower()
    transport.notification(channels[1], bytes.fromhex("F5 22 00 EF"))
    panel.stop_button.click()
    assert "off" in viewer.recording_label.text().lower()
    transport.notification(channels[0], bytes.fromhex("F5 33 00 EF"))

    assert viewer.received_count == 3
    for payload in ("F5 11 00 EF", "F5 22 00 EF", "F5 33 00 EF"):
        assert viewer.packets.toPlainText().count(payload) == 1
        assert panel.packets.toPlainText().count(payload) == 1
    rows = [json.loads(line) for line in panel.last_path.read_text(encoding="utf-8").splitlines()]
    recorded = [row for row in rows if row["type"] == "notification"]
    assert len(recorded) == 1 and recorded[0]["hex"] == "F5 22 00 EF"
    assert rows[-1]["type"] == "session_end" and rows[-1]["packet_count"] == 1
    window.actions.execute.assert_not_called()


def test_health_heartbeat_updates_view_without_diagnostics_or_capture_spam(window):
    window.on_transport_event("status", "Connected · waiting for first packet")
    window.capture_panel.start_recording()
    log_before = window.log.toPlainText()
    rows_before = window.capture_panel.last_path.read_text(encoding="utf-8")
    window.on_transport_event("connection_health", health())
    window.on_transport_event("connection_health", health("receiving", packet_count=7, age=2.5))

    assert window.log.toPlainText() == log_before
    assert window.capture_panel.last_path.read_text(encoding="utf-8") == rows_before
    assert "last RX 2.5 s ago" in window.packet_viewer.health_label.text()
    assert "7 live RX in current connection" in window.packet_viewer.health_label.text()


def test_sensor_request_is_distinguished_from_actual_gestures_and_is_recorded(window):
    window.on_transport_event("status", "Connected · waiting for first packet")
    window.capture_panel.start_recording()
    requested = {"connection_id": "test-connection", "state": "requested", "detail": "Enable request sent"}
    window.on_transport_event("sensor_state", requested)
    viewer = window.packet_viewer
    assert "waiting for gesture packets" in viewer.sensor_label.text()
    transport = Transport(window.on_transport_event)
    channel = SimpleNamespace(uuid=sorted(NOTIFY)[0])
    # Unknown code 0A stays visible but does not establish gesture readiness.
    transport.notification(channel, bytes.fromhex("00 09 61 00 0A 00 00 01 00 00 00"))
    assert viewer.live_count == 1 and not viewer.gesture_received
    assert "waiting for gesture packets" in viewer.sensor_label.text()
    transport.notification(channel, bytes.fromhex("00 09 61 00 01 00 00 02 00 00 00"))
    assert viewer.live_count == 2 and viewer.gesture_received
    assert "real gesture packets received" in viewer.sensor_label.text()
    window.on_transport_event("sensor_state", requested)
    assert "real gesture packets received" in viewer.sensor_label.text()
    assert not window.enable.isChecked()
    window.capture_panel.stop_recording()
    rows = [json.loads(line) for line in window.capture_panel.last_path.read_text(encoding="utf-8").splitlines()]
    sensor_events = [row for row in rows if row.get("kind") == "sensor_state"]
    assert len(sensor_events) == 2
    window.on_transport_event("status", "Disconnected")
    assert not viewer.gesture_received
    assert "waiting for a connection" in viewer.sensor_label.text()


def test_sensor_failure_remains_visible_while_unknown_raw_packets_are_displayed(window):
    window.on_transport_event("sensor_state", {"state": "error", "detail": "write timeout"})
    assert "activation failed" in window.packet_viewer.sensor_label.text()
    assert "write timeout" in window.packet_viewer.sensor_label.text()
    transport = Transport(window.on_transport_event)
    transport.notification(SimpleNamespace(uuid=sorted(NOTIFY)[0]), b"\xEE\x00")
    assert window.packet_viewer.live_count == 1
    assert "activation failed" in window.packet_viewer.sensor_label.text()


def test_subscription_refresh_requires_an_active_connected_worker(window):
    window.worker = SimpleNamespace(isRunning=Mock(return_value=True), refresh_notifications=Mock())
    window.refresh_notifications()
    window.worker.refresh_notifications.assert_not_called()
    window.on_transport_event("status", "Connected · waiting for first packet")
    assert window.packet_viewer.refresh_button.isEnabled()
    window.packet_viewer.refresh_button.click()
    window.worker.refresh_notifications.assert_called_once_with()
    window.worker.isRunning.return_value = False
    window.refresh_notifications()
    window.worker.refresh_notifications.assert_called_once_with()
    window.on_transport_event("status", "Disconnected")
    assert not window.packet_viewer.refresh_button.isEnabled()


def test_worker_schedules_refresh_on_its_event_loop_and_handles_stopped_worker(monkeypatch):
    worker = ui.Worker("test-address")
    worker.loop = SimpleNamespace(call_soon_threadsafe=Mock())
    worker.transport = SimpleNamespace(request_refresh=Mock())
    monkeypatch.setattr(worker, "isRunning", lambda: True)
    assert worker.refresh_notifications()
    worker.loop.call_soon_threadsafe.assert_called_once_with(worker.transport.request_refresh)
    worker.cancelled = True
    assert not worker.refresh_notifications()
    worker.cancelled = False
    worker.loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
    assert not worker.refresh_notifications()
    monkeypatch.setattr(worker, "isRunning", lambda: False)
    assert not worker.refresh_notifications()


def test_real_worker_thread_delivers_raw_notifications_to_main_window(window, app, monkeypatch):
    gui_thread = threading.get_ident()
    emission_threads = []
    class ThreadTransport(Transport):
        async def run(self, address, **kwargs):
            emission_threads.append(threading.get_ident())
            for uuid in sorted(NOTIFY):
                self.notification(SimpleNamespace(uuid=uuid), bytes.fromhex("F5 11 AA 77 EF"))

    monkeypatch.setattr(ui, "Transport", ThreadTransport)
    loop = QEventLoop()
    window.start_worker("test-address")
    worker = window.worker
    worker.finished.connect(loop.quit)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    timeout.stop()
    assert worker.wait(2000)
    app.processEvents()

    assert emission_threads and emission_threads[0] != gui_thread
    assert window.packet_viewer.live_count == window.packet_viewer.received_count == 2
    assert window.packet_viewer.imported_count == 0
    assert window.packet_viewer.packets.toPlainText().count("F5 11 AA 77 EF") == 2
    assert window.packet_viewer.packets.toPlainText().count("RX") == 2
