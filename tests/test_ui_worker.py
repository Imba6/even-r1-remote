"""Exercise real Qt signals/threads; a mocked publisher hid the original bug."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from even_r1 import ui
from even_r1.settings import Settings


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for_worker(app, window):
    deadline = time.monotonic() + 5
    while not window.scan_button.isEnabled():
        app.processEvents()
        assert time.monotonic() < deadline, "Qt worker did not finish"
        time.sleep(.005)
    app.processEvents()


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "Settings", lambda: Settings(tmp_path / "settings.json"))
    w = ui.Window()
    yield w
    if w.worker:
        w.worker.stop()
        w.worker.wait(5000)
    w.quitting = True
    w.tray.hide()
    w.close()


@pytest.mark.parametrize("rings", [[], [(SimpleNamespace(address="AA:BB:CC:DD:EE:FF"), "EVEN R1_test", -55)]])
def test_scan_button_delivers_real_worker_signals(app, window, monkeypatch, rings):
    async def scan(transport, timeout=8):
        transport.emit("status", "Scanning")
        await asyncio.sleep(.02)
        return rings
    monkeypatch.setattr(ui.Transport, "scan", scan)
    for _ in range(2):
        window.scan_button.click()
        assert not window.scan_button.isEnabled()
        wait_for_worker(app, window)
        assert "Scanning" in window.log.toPlainText()
        assert window.status.text().startswith("Scan complete")
        if rings:
            assert window.devices.currentData() == "AA:BB:CC:DD:EE:FF"
        else:
            assert "no ring found" in window.status.text()


def test_scan_failure_stays_visible_after_thread_exits(app, window, monkeypatch):
    async def scan(transport, timeout=8):
        transport.emit("status", "Scanning")
        raise RuntimeError("Radio unavailable for test")
    monkeypatch.setattr(ui.Transport, "scan", scan)
    window.scan_button.click()
    wait_for_worker(app, window)
    assert window.status.text() == "Bluetooth unavailable"
    assert "Radio unavailable for test" in window.log.toPlainText()
    assert window.scan_button.isEnabled()
