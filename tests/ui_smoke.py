import tempfile
from pathlib import Path
# Render with the Windows platform and installed fonts
from PySide6.QtWidgets import QApplication
from even_r1 import ui
from even_r1.settings import Settings
from even_r1.ui import Window, STYLE
temporary_settings = tempfile.TemporaryDirectory()
ui.Settings = lambda: Settings(Path(temporary_settings.name) / 'settings.json')
app=QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
w=Window(); w.show(); app.processEvents()
w.grab().save('docs/desktop.png')
assert w.status.text()=='Disconnected'
assert not w.actions.enabled
w.profile.setCurrentText('Presentation'); app.processEvents()
assert w.rows[next(iter(w.rows))][1].text()=='f5'
w.profile.setCurrentText('Default')
w.quitting=True; w.close(); w.tray.hide()
temporary_settings.cleanup()
print('UI smoke passed')

