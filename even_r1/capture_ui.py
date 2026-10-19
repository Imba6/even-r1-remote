"""Local raw capture and timed, explicitly labelled gesture trials."""
import logging
from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit, QMessageBox)
from .capture import CaptureSession
from .protocol import Gesture


class CapturePanel(QWidget):
    recording_changed = Signal(bool)

    def __init__(self, metadata_provider=lambda: {}, directory=None, parent=None):
        super().__init__(parent)
        self.metadata_provider = metadata_provider
        self.directory = directory
        self.session = None
        self.last_path = None
        self.connected = False
        self.phase = "idle"
        self.remaining = 0
        self.repetition = 0
        self.total = 0
        self.trial_label = ""
        self.open_trial = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        layout = QVBoxLayout(self)
        hint = QLabel("Record every notification, then repeat one action at a time. Labels describe your intended action, not a decoded result.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start recording")
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button = QPushButton("Stop & save")
        self.stop_button.clicked.connect(lambda: self.stop_recording())
        self.folder_button = QPushButton("Open capture folder")
        self.folder_button.clicked.connect(self.open_folder)
        for widget in (self.start_button, self.stop_button, self.folder_button):
            buttons.addWidget(widget)
        layout.addLayout(buttons)
        self.path_label = QLabel("No recording yet · files stay on this PC")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.count_label = QLabel("0 packets recorded")
        layout.addWidget(self.count_label)
        trials = QHBoxLayout()
        self.action_label = QComboBox()
        self.action_label.setEditable(True)
        self.action_label.addItems([str(g) for g in Gesture])
        self.repeats = QSpinBox()
        self.repeats.setRange(1, 10)
        self.repeats.setValue(5)
        self.repeats.setSuffix(" repeats")
        self.series_button = QPushButton("Run selected action")
        self.series_button.clicked.connect(self.start_series)
        self.cancel_button = QPushButton("Cancel series")
        self.cancel_button.clicked.connect(lambda: self.cancel_series("user"))
        for widget in (self.action_label, self.repeats, self.series_button, self.cancel_button):
            trials.addWidget(widget)
        layout.addLayout(trials)
        self.instruction = QLabel("Connect the ring, start recording, then run a series.")
        self.instruction.setWordWrap(True)
        self.instruction.setStyleSheet("font-size: 19px; color: #91e5c0; padding: 12px 0;")
        layout.addWidget(self.instruction)
        timing = QLabel("Each series: 5 s rest baseline, then 3 s countdown → 5 s action window → 3 s rest for each repetition. Perform the action once in each action window.")
        timing.setWordWrap(True)
        layout.addWidget(timing)
        annotations = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional marker, e.g. ring removed / finger changed")
        self.marker_button = QPushButton("Add marker")
        self.marker_button.clicked.connect(self.add_marker)
        annotations.addWidget(self.note, 1)
        annotations.addWidget(self.marker_button)
        layout.addLayout(annotations)
        self.packets = QPlainTextEdit()
        self.packets.setReadOnly(True)
        self.packets.document().setMaximumBlockCount(0)
        self.packets.setPlaceholderText("Actual BLE notifications appear here. Start recording saves new packets to JSONL. All received packets remain visible, including duplicates and unknown formats.")
        layout.addWidget(self.packets, 1)
        self.refresh()

    @property
    def recording(self):
        return self.session is not None and self.session.active

    def refresh(self):
        active = self.recording
        running = self.phase != "idle"
        self.start_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.folder_button.setEnabled(self.last_path is not None)
        self.series_button.setEnabled(active and self.connected and not running)
        self.cancel_button.setEnabled(running)
        self.action_label.setEnabled(not running)
        self.repeats.setEnabled(not running)
        self.marker_button.setEnabled(active)

    def start_recording(self):
        if self.recording:
            return
        try:
            self.session = CaptureSession(self.directory, self.metadata_provider())
            self.last_path = self.session.path
            self.session.event("connection_at_start", "connected" if self.connected else "not connected")
        except OSError as exc:
            self.failed(exc)
            return
        self.path_label.setText(f"Recording: {self.last_path}")
        self.count_label.setText("0 packets recorded")
        self.instruction.setText("Recording. Choose one action and run a series when the ring is connected.")
        self.recording_changed.emit(True)
        self.refresh()

    def stop_recording(self, reason="user"):
        if self.session is None:
            return
        try:
            self.cancel_series(reason)
            self.session.stop(reason)
        except OSError as exc:
            self.failed(exc)
            return
        self.path_label.setText(f"Saved: {self.last_path}")
        self.instruction.setText("Recording saved. No gesture meanings have been inferred automatically.")
        self.recording_changed.emit(False)
        self.refresh()

    def feed(self, kind, value):
        if kind == "status":
            self.connected = value.startswith("Connected")
            if not self.connected and self.phase != "idle":
                self.cancel_series("connection lost")
        try:
            if kind == "raw_packet":
                if self.recording:
                    self.session.record_packet(value)
                    self.count_label.setText(f"{self.session.packet_count} packets recorded")
                self.packets.appendPlainText(f"{value['timestamp_utc']}  {value['characteristic']}  {value['length']} B\n{value['hex']}")
            elif self.recording and kind in {"status", "gatt", "log", "battery", "gesture", "sensor_state"}:
                self.session.event(kind, value)
        except OSError as exc:
            self.failed(exc)
        self.refresh()

    def start_series(self):
        if not self.recording or not self.connected or self.phase != "idle":
            return
        label = self.action_label.currentText().strip()
        if not label or len(label) > 200:
            QMessageBox.warning(self, "Action label", "Enter an action label of 1–200 characters.")
            return
        self.trial_label = label
        self.total = self.repeats.value()
        self.repetition = 1
        try:
            self.session.event("series_start", {"label": label, "repeats": self.total, "baseline_s": 5, "countdown_s": 3, "action_s": 5, "rest_s": 3})
            self.begin_phase("baseline", 5, "Rest / no action")
        except OSError as exc:
            self.failed(exc)
            return
        self.timer.start()
        self.refresh()

    def begin_phase(self, phase, seconds, label=None):
        if self.open_trial is not None:
            old_label, old_rep = self.open_trial
            self.session.marker(old_label, old_rep, "trial_end")
            self.open_trial = None
        self.phase, self.remaining = phase, seconds
        if label:
            rep = self.repetition if phase == "action" else None
            self.session.marker(label, rep, "trial_start")
            self.open_trial = (label, rep)
        else:
            self.session.event("countdown", {"label": self.trial_label, "repetition": self.repetition})
        self.render_instruction()

    def render_instruction(self):
        if self.phase == "baseline":
            text = f"REST · do nothing for {self.remaining} s"
        elif self.phase == "prepare":
            text = f"Get ready: {self.trial_label} · {self.repetition}/{self.total} · {self.remaining} s"
        elif self.phase == "action":
            text = f"DO ONCE: {self.trial_label} · {self.repetition}/{self.total} · {self.remaining} s"
        else:
            text = f"REST · {self.remaining} s"
        self.instruction.setText(text)

    def tick(self):
        if self.phase == "idle":
            return
        self.remaining -= 1
        if self.remaining > 0:
            self.render_instruction()
            return
        try:
            if self.phase == "baseline":
                self.begin_phase("prepare", 3)
            elif self.phase == "prepare":
                self.begin_phase("action", 5, self.trial_label)
            elif self.phase == "action":
                self.begin_phase("rest", 3, "Rest / no action")
            elif self.repetition < self.total:
                self.repetition += 1
                self.begin_phase("prepare", 3)
            else:
                label, rep = self.open_trial
                self.session.marker(label, rep, "trial_end")
                self.open_trial = None
                self.session.event("series_complete", {"label": self.trial_label, "repeats": self.total})
                self.phase = "idle"
                self.timer.stop()
                self.instruction.setText(f"Series complete: {self.trial_label} × {self.total}. Choose the next action, or Stop & save.")
                self.refresh()
        except OSError as exc:
            self.failed(exc)

    def cancel_series(self, reason):
        if self.phase == "idle":
            return
        self.timer.stop()
        try:
            if self.recording:
                if self.open_trial:
                    label, rep = self.open_trial
                    self.session.marker(label, rep, "trial_end")
                self.session.event("series_cancelled", {"reason": reason, "label": self.trial_label, "repetition": self.repetition, "phase": self.phase})
        except OSError as exc:
            self.failed(exc)
            return
        self.open_trial = None
        self.phase = "idle"
        self.instruction.setText(f"Series cancelled: {reason}. Recording continues until Stop & save.")
        self.refresh()

    def add_marker(self):
        label = self.note.text().strip()
        if self.recording and label:
            try:
                self.session.marker(label[:200])
                self.note.clear()
            except OSError as exc:
                self.failed(exc)

    def open_folder(self):
        if self.last_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_path.parent)))

    def failed(self, exc):
        logging.exception("Data capture failed")
        self.timer.stop()
        self.phase = "idle"
        self.open_trial = None
        if self.session is not None:
            try:
                self.session.stop("write error")
            except OSError:
                pass
        self.instruction.setText(f"Recording stopped: {exc}")
        self.recording_changed.emit(False)
        self.refresh()
        QMessageBox.warning(self, "Recording failed", str(exc))
