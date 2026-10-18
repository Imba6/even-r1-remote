import asyncio
import copy
import logging
import sys
from datetime import datetime
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox, QSpinBox, QTabWidget,
    QPlainTextEdit, QGridLayout, QSystemTrayIcon, QMenu, QMessageBox, QInputDialog,
    QFileDialog, QFrame)
from .ble import Transport
from .settings import Settings, ACTIONS, ROOT, setup_logging
from .actions import Actions
from .protocol import Gesture
from .startup import startup_enabled, set_startup

class Worker(QThread):
    event = Signal(str, object)
    def __init__(self, address=None):
        super().__init__()
        self.address = address
        self.loop = None
        self.transport = None
        self.cancelled = False
    def emit(self, kind, value):
        logging.info("%s %s", kind, value)
        self.event.emit(kind, value)
    def run(self):
        async def work():
            self.loop = asyncio.get_running_loop()
            self.transport = Transport(self.emit)
            if self.cancelled: return
            try:
                if self.address: await self.transport.run(self.address)
                else: self.emit("devices", await self.transport.scan())
            except Exception as exc:
                logging.exception("Bluetooth worker")
                self.emit("log", str(exc))
                self.emit("status", "Bluetooth unavailable")
        asyncio.run(work())
    def stop(self):
        self.cancelled = True
        if self.loop and self.transport:
            try: self.loop.call_soon_threadsafe(self.transport.stop.set)
            except RuntimeError: pass

class Ring(QWidget):
    def __init__(self):
        super().__init__()
        self.active = False
        self.setMinimumSize(180, 160)
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = self.width() // 2, self.height() // 2
        p.setPen(QPen(QColor("#91e5c0" if self.active else "#45524e"), 17))
        p.drawEllipse(x-48, y-57, 96, 114)
        p.setPen(QPen(QColor("#c0f6dd" if self.active else "#7c8c85"), 2))
        p.drawArc(x-48, y-57, 96, 114, 30*16, 110*16)
    def pulse(self):
        self.active = True
        self.update()
        QTimer.singleShot(400, self.reset)
    def reset(self):
        self.active = False
        self.update()

def button(text, fn):
    b = QPushButton(text)
    b.clicked.connect(fn)
    return b

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.actions = Actions(self.settings)
        self.worker = None
        self.quitting = False
        self.setWindowTitle("Even R1 Remote")
        self.resize(1000, 790)
        self.setMinimumSize(840, 680)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 25, 32, 24)
        header = QHBoxLayout()
        title = QLabel("R1  /  REMOTE")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        self.enable = QCheckBox("Enable Windows controls")
        self.enable.toggled.connect(lambda v: setattr(self.actions, "enabled", v))
        header.addWidget(self.enable)
        layout.addLayout(header)
        subtitle = QLabel("A little gesture. A natural way to control your desktop.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        card = QFrame()
        card.setObjectName("card")
        top = QHBoxLayout(card)
        self.ring = Ring()
        top.addWidget(self.ring)
        details = QVBoxLayout()
        self.status = QLabel("Disconnected")
        self.status.setObjectName("heading")
        details.addWidget(self.status)
        self.battery = QLabel("Battery —   ·   Signal —")
        details.addWidget(self.battery)
        self.last = QLabel("Waiting for a real ring gesture")
        details.addWidget(self.last)
        details.addWidget(QLabel("BLE only  ·  No cloud  ·  No firmware changes"))
        top.addLayout(details, 1)
        layout.addWidget(card)
        connect = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.setMinimumWidth(390)
        self.devices.addItem("Scan to find your Even R1", "")
        connect.addWidget(self.devices, 1)
        self.scan_button = button("Scan for ring", self.scan)
        connect.addWidget(self.scan_button)
        self.connect_button = button("Connect", self.connect_ring)
        connect.addWidget(self.connect_button)
        self.disconnect_button = button("Disconnect", self.disconnect_ring)
        connect.addWidget(self.disconnect_button)
        layout.addLayout(connect)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        mapping = QWidget()
        ml = QVBoxLayout(mapping)
        profiles = QHBoxLayout()
        profiles.addWidget(QLabel("PROFILE"))
        self.profile = QComboBox()
        self.profile.addItems(self.settings.data["profiles"])
        self.profile.setCurrentText(self.settings.data["profile"])
        self.profile.currentTextChanged.connect(self.change_profile)
        profiles.addWidget(self.profile, 1)
        profiles.addWidget(button("Duplicate profile", self.duplicate_profile))
        ml.addLayout(profiles)
        grid = QGridLayout()
        grid.addWidget(QLabel("GESTURE"), 0, 0)
        grid.addWidget(QLabel("ACTION"), 0, 1)
        grid.addWidget(QLabel("CUSTOM SHORTCUT"), 0, 2)
        self.rows = {}
        for i, g in enumerate(Gesture, 1):
            label = QLabel(g)
            action = QComboBox()
            action.addItems(ACTIONS)
            key = QLineEdit()
            key.setPlaceholderText("e.g. ctrl+shift+s")
            grid.addWidget(label, i, 0)
            grid.addWidget(action, i, 1)
            grid.addWidget(key, i, 2)
            self.rows[g] = (action, key, label)
            action.currentTextChanged.connect(lambda _, gesture=g: self.save_mapping(gesture))
            key.editingFinished.connect(lambda gesture=g: self.save_mapping(gesture))
        ml.addLayout(grid)
        ml.addWidget(QLabel("Shortcuts: ctrl, alt, shift, win, enter, esc, arrows, f1–f20, or a character."))
        ml.addStretch()
        self.tabs.addTab(mapping, "Gesture mappings")
        prefs = QWidget()
        pl = QVBoxLayout(prefs)
        for text, key in [("Reconnect to saved ring on launch", "auto_connect"), ("Minimize to system tray when closing", "minimize_tray"), ("Accelerate repeated scrolling", "acceleration")]:
            cb = QCheckBox(text)
            cb.setChecked(self.settings.data[key])
            cb.toggled.connect(lambda value, k=key: self.preference(k, value))
            pl.addWidget(cb)
        startup = QCheckBox("Launch on Windows startup")
        startup.setChecked(startup_enabled())
        startup.toggled.connect(self.startup)
        pl.addWidget(startup)
        for text, key, lo, hi in [("Scroll steps", "scroll_steps", 1, 20), ("Gesture debounce (ms)", "debounce_ms", 0, 2000)]:
            row = QHBoxLayout()
            row.addWidget(QLabel(text))
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(self.settings.data[key])
            spin.valueChanged.connect(lambda value, k=key: self.preference(k, value))
            row.addWidget(spin)
            pl.addLayout(row)
        pl.addWidget(QLabel("Controls start paused each launch. Enable them after checking live gestures.\nRSSI is the last scan measurement; battery requires standard GATT support."))
        pl.addStretch()
        self.tabs.addTab(prefs, "Preferences")
        diag = QWidget()
        dl = QVBoxLayout(diag)
        dl.addWidget(QLabel("Live GATT, notification bytes and decoder events. No initialization commands are sent."))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(1500)
        dl.addWidget(self.log)
        dl.addWidget(button("Export diagnostic log…", self.export))
        self.tabs.addTab(diag, "Diagnostics")
        footer = QLabel("INDEPENDENT PROJECT     /     Hardware compatibility awaits real notification validation")
        footer.setObjectName("muted")
        layout.addWidget(footer)
        self.load_mapping()
        self.tray = QSystemTrayIcon(self.icon(), self)
        menu = QMenu()
        menu.addAction("Open R1 Remote", self.showNormal)
        pause = menu.addAction("Pause controls")
        pause.triggered.connect(lambda: self.enable.setChecked(False))
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Even R1 Remote")
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.setWindowIcon(self.icon())
        if self.settings.data["auto_connect"] and self.settings.data["address"]:
            QTimer.singleShot(300, lambda: self.start_worker(self.settings.data["address"]))
    def icon(self):
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#91e5c0"), 8))
        p.drawEllipse(15, 7, 34, 50)
        p.end()
        return QIcon(pix)
    def preference(self, key, value):
        self.settings.data[key] = value
        self.persist()
    def persist(self):
        try: self.settings.save()
        except OSError as exc: QMessageBox.warning(self, "Settings could not be saved", str(exc))
    def startup(self, value):
        try: set_startup(value)
        except OSError as exc: QMessageBox.warning(self, "Startup registration", str(exc))
    def load_mapping(self):
        for g, (action, key, _) in self.rows.items():
            value = self.settings.data["profiles"][self.settings.data["profile"]][g]
            action.blockSignals(True)
            action.setCurrentText(value["action"])
            action.blockSignals(False)
            key.setText(value["hotkey"])
            key.setEnabled(value["action"] == "Keyboard shortcut")
    def save_mapping(self, gesture):
        action, key, _ = self.rows[gesture]
        key.setEnabled(action.currentText() == "Keyboard shortcut")
        if action.currentText() == "Keyboard shortcut" and key.text():
            try: Actions.parse_hotkey(key.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid shortcut", str(exc))
                return
        self.settings.data["profiles"][self.settings.data["profile"]][gesture] = {"action": action.currentText(), "hotkey": key.text()}
        self.persist()
    def change_profile(self, name):
        self.preference("profile", name)
        self.actions.last.clear()
        self.load_mapping()
    def duplicate_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name")
        name = name.strip()
        if ok and name and name not in self.settings.data["profiles"]:
            self.settings.data["profiles"][name] = copy.deepcopy(self.settings.data["profiles"][self.settings.data["profile"]])
            self.profile.addItem(name)
            self.profile.setCurrentText(name)
    def start_worker(self, address=None):
        if self.worker and self.worker.isRunning(): return
        self.worker = Worker(address)
        self.worker.event.connect(self.on_transport_event)
        self.worker.finished.connect(self.finished)
        self.scan_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.worker.start()
    def finished(self):
        self.scan_button.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.status.setText("Disconnected")
        self.battery.setText("Battery —   ·   Signal —")
    def scan(self): self.start_worker()
    def connect_ring(self):
        address = self.devices.currentData()
        if address:
            self.preference("address", address)
            self.start_worker(address)
        else: QMessageBox.information(self, "Select a ring", "Scan, then select your advertised Even R1.")
    def disconnect_ring(self):
        self.enable.setChecked(False)
        if self.worker: self.worker.stop()
        self.status.setText("Disconnecting")
    def on_transport_event(self, kind, value):
        stamp = datetime.now().strftime("%H:%M:%S")
        if kind == "devices":
            self.devices.clear()
            for device, name, rssi in value:
                self.devices.addItem(f"{name}  ·  {device.address}  ·  {rssi} dBm (scan)", device.address)
            if not value: self.devices.addItem("No ring found · wake ring and scan again", "")
        elif kind == "status":
            self.status.setText(value)
            if not value.startswith("Connected"):
                self.battery.setText("Battery —   ·   Signal: see last scan")
        elif kind == "battery": self.battery.setText(f"Battery {str(value) + '%' if value is not None else '—'}   ·   Signal: see last scan")
        elif kind == "gesture":
            self.ring.pulse()
            try: result = self.actions.execute(value.gesture)
            except Exception as exc:
                self.enable.setChecked(False)
                result = f"Input paused: {exc}"
                logging.exception("Input action failed")
            self.last.setText(f"{value.gesture}  →  {result}")
            for g, (_, _, label) in self.rows.items():
                label.setStyleSheet("color: #91e5c0; font-weight: 600" if g == value.gesture else "")
        self.log.appendPlainText(f"{stamp}  {kind.upper()}  {value}")
    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics", "r1-diagnostics.txt", "Text (*.txt)")
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(self.log.toPlainText(), encoding="utf-8")
            except OSError as exc: QMessageBox.warning(self, "Export failed", str(exc))
    def closeEvent(self, event):
        if not self.quitting and self.settings.data["minimize_tray"] and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        elif self.worker and self.worker.isRunning():
            self.quit()
            event.ignore()
        else: event.accept()
    def quit(self):
        self.quitting = True
        self.enable.setChecked(False)
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status.setText("Closing Bluetooth session…")
            QTimer.singleShot(250, self.quit)
        else:
            self.tray.hide()
            QApplication.quit()

STYLE = """
QWidget { background: #111615; color: #dce5df; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#title { font-size: 28px; font-weight: 600; letter-spacing: 3px; }
QLabel#heading { font-size: 23px; font-weight: 600; }
QLabel#muted { color: #82958b; font-size: 12px; }
QFrame#card { background: #1a2420; border: 1px solid #2e3d35; border-radius: 14px; }
QFrame#card QWidget { background: transparent; }
QPushButton, QComboBox, QLineEdit, QSpinBox { background: #202c26; border: 1px solid #3b4d42; border-radius: 6px; padding: 8px; }
QPushButton:hover { background: #365244; border-color: #91e5c0; }
QPushButton:disabled { color: #66746b; }
QCheckBox { padding: 8px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #65796b; border-radius: 4px; background: #1a2420; }
QCheckBox::indicator:checked { background: #91e5c0; }
QTabWidget::pane { border: 1px solid #2e3d35; border-radius: 6px; padding: 14px; }
QTabBar::tab { padding: 12px 20px; color: #82958b; }
QTabBar::tab:selected { color: #91e5c0; border-bottom: 2px solid #91e5c0; }
QPlainTextEdit { font-family: Consolas; font-size: 12px; background: #0c100e; border: none; }
"""
def main():
    setup_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(1200, window.quit)
    sys.exit(app.exec())

