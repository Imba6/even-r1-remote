"""Complete raw notification history for visual inspection."""
import json
from pathlib import Path
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QCheckBox, QPlainTextEdit, QFileDialog, QMessageBox)


class LivePacketViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.received_count = 0
        self.live_count = 0
        self.imported_count = 0
        self.connection_id = None
        self.connection_packet_count = 0
        self.connected = False
        self.gesture_received = False
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.count_label = QLabel("0 packets displayed · 0 live RX · 0 imported FILE")
        tools.addWidget(self.count_label)
        tools.addStretch()
        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)
        tools.addWidget(self.auto_scroll)
        load = QPushButton("Load JSONL…")
        load.clicked.connect(self.open_capture)
        tools.addWidget(load)
        export = QPushButton("Export all text…")
        export.clicked.connect(self.export_view)
        tools.addWidget(export)
        layout.addLayout(tools)
        find = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find bytes, channel or timestamp · e.g. 00 1A 89")
        self.search.returnPressed.connect(self.find_next)
        find.addWidget(self.search, 1)
        next_button = QPushButton("Find next")
        next_button.clicked.connect(self.find_next)
        find.addWidget(next_button)
        layout.addLayout(find)
        self.recording_label = QLabel()
        self.set_recording(False)
        layout.addWidget(self.recording_label)
        self.sensor_label = QLabel("Gesture sensor: waiting for a connection")
        self.sensor_label.setWordWrap(True)
        layout.addWidget(self.sensor_label)
        health = QHBoxLayout()
        self.health_label = QLabel("Disconnected · no live packets received in this connection")
        self.health_label.setWordWrap(True)
        health.addWidget(self.health_label, 1)
        self.refresh_button = QPushButton("Refresh subscriptions")
        self.refresh_button.setEnabled(False)
        self.refresh_button.setToolTip("Re-subscribe to both ring notification channels on the current connection")
        health.addWidget(self.refresh_button)
        layout.addLayout(health)
        self.source_label = QLabel("All received notifications stay here until the application closes. Unknown and duplicate packets are included.")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.packets = QPlainTextEdit()
        self.packets.setReadOnly(True)
        self.packets.setUndoRedoEnabled(False)
        self.packets.document().setMaximumBlockCount(0)
        self.packets.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.packets.setPlaceholderText("Connect the ring. Every received notification from BAE80011 and BAE80013 appears here, whether file recording is on or off.")
        layout.addWidget(self.packets, 1)
        self.auto_scroll.toggled.connect(self.follow_latest)
        self.packets.verticalScrollBar().rangeChanged.connect(
            lambda low, high: self.follow_latest(self.auto_scroll.isChecked()))

    def set_recording(self, active):
        self.recording_label.setText("File recording: ON · new live packets are being saved" if active
            else "File recording: OFF · live packets are still displayed")
        self.recording_label.setStyleSheet("color: #91e5c0;" if active else "color: #e8c18b;")

    def follow_latest(self, active):
        if active:
            bar = self.packets.verticalScrollBar()
            bar.setValue(bar.maximum())

    def set_connection_status(self, status):
        self.connected = status.startswith("Connected")
        self.refresh_button.setEnabled(self.connected)
        if not self.connected:
            self.health_label.setText(f"{status} · {self.connection_packet_count} live RX in last connection")
            self.gesture_received = False
            self.sensor_label.setText("Gesture sensor: waiting for a connection")
            self.sensor_label.setStyleSheet("")
        elif self.connection_packet_count == 0:
            self.health_label.setText("Connected · waiting for first packet · 0 live RX in current connection")

    def set_sensor_state(self, state):
        if self.gesture_received:
            return
        messages = {
            "enabling": "Gesture sensor: sending enable request…",
            "requested": "Gesture sensor: enable request sent · waiting for gesture packets",
            "unavailable": "Gesture sensor: unavailable",
            "error": "Gesture sensor: activation failed",
        }
        message = messages.get(state["state"], "Gesture sensor: waiting for a connection")
        if state["state"] in {"error", "unavailable"} and state.get("detail"):
            message += " · " + state["detail"]
        self.sensor_label.setText(message)
        self.sensor_label.setStyleSheet("color: #e8c18b;")

    def note_gesture(self):
        self.gesture_received = True
        self.sensor_label.setText("Gesture sensor: real gesture packets received")
        self.sensor_label.setStyleSheet("color: #91e5c0;")

    def set_connection_health(self, health):
        connection_id = health.get("connection_id")
        if connection_id != self.connection_id:
            self.connection_id = connection_id
            self.connection_packet_count = 0
            self.gesture_received = False
        self.connection_packet_count = health["packet_count"]
        phase = health["phase"]
        self.connected = phase in {"waiting", "receiving", "refreshing"}
        self.refresh_button.setEnabled(self.connected and phase != "refreshing")
        count = self.connection_packet_count
        channels = health["subscribed_count"]
        if phase == "subscribing":
            message = f"Subscribing · {channels} channel(s) ready"
        elif phase == "refreshing":
            message = "Refreshing notification subscriptions…"
        elif phase == "disconnected":
            message = "Disconnected"
        elif count == 0:
            message = f"Subscribed on {channels} channel(s) · waiting for first packet"
        else:
            age = health.get("seconds_since_last_packet")
            age_text = f"{age:.1f} s ago" if age is not None else "time unavailable"
            message = f"Subscribed on {channels} channel(s) · last RX {age_text}"
        self.health_label.setText(f"{message} · {count} live RX in current connection")
        self.health_label.setStyleSheet("color: #91e5c0;" if count and self.connected else "color: #e8c18b;")

    def append_packet(self, packet, origin="live"):
        bar = self.packets.verticalScrollBar()
        xbar = self.packets.horizontalScrollBar()
        position, xpos = bar.value(), xbar.value()
        self.received_count += 1
        source = "FILE" if origin == "file" else "RX"
        if origin == "file":
            self.imported_count += 1
        else:
            self.live_count += 1
        text = (f"#{self.received_count:06d}  {packet['timestamp_utc']}  {source}  "
                f"{packet['characteristic']}  {packet['length']} B\n"
                f"{packet['hex'] or '(empty payload)'}")
        cursor = QTextCursor(self.packets.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(("\n\n" if not self.packets.document().isEmpty() else "") + text)
        self.count_label.setText(f"{self.received_count} packets displayed · {self.live_count} live RX · {self.imported_count} imported FILE")
        if self.auto_scroll.isChecked():
            self.follow_latest(True)
        else:
            bar.setValue(position)
            xbar.setValue(xpos)

    def find_next(self):
        text = self.search.text()
        if not text:
            return
        self.auto_scroll.setChecked(False)
        if not self.packets.find(text):
            cursor = self.packets.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.packets.setTextCursor(cursor)
            self.packets.find(text)

    def load_capture(self, path):
        count = 0
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict) or row.get("type") != "notification":
                    continue
                if not all(isinstance(row.get(key), str) for key in ("timestamp_utc", "characteristic", "hex")) or type(row.get("length")) is not int:
                    raise ValueError("A notification record is missing its timestamp, channel, length or hex bytes")
                self.append_packet(row, origin="file")
                count += 1
        self.source_label.setText(f"Loaded {count} packets from {Path(path).name} (FILE). New notifications appear as RX; existing history stays visible.")
        return count

    def open_capture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load captured notifications", "", "JSONL (*.jsonl);;All files (*)")
        if path:
            try:
                self.load_capture(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Could not load capture", str(exc))

    def export_view(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export all displayed packets", "r1-all-packets.txt", "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self.packets.toPlainText(), encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Export failed", str(exc))
