import os
# Render with the Windows platform and installed fonts
from PySide6.QtWidgets import QApplication
from even_r1.ui import Window, STYLE
app=QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
w=Window(); w.show(); app.processEvents()
w.grab().save('docs/desktop.png')
assert w.status.text()=='Disconnected'
assert not w.actions.enabled
w.profile.setCurrentText('Presentation'); app.processEvents()
assert w.rows[next(iter(w.rows))][1].text()=='f5'
w.profile.setCurrentText('Default')
w.quitting=True; w.close(); w.tray.hide()
print('UI smoke passed')

