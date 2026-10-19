"""Exercise the complete packet history with real Qt widgets and mock BLE data.

No Bluetooth connection or Windows input controller is created. Notifications
pass through the same raw-packet event path as a connected ring.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
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
