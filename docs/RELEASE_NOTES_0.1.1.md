# v0.1.1 — Fix unresponsive Scan button

Fix a Qt method-name collision that prevented worker signals from being delivered.
The Scan button now starts BLE discovery and shows a final result. Scan failures
remain visible after the worker exits instead of being replaced by Disconnected.
Diagnostics distinguishes total BLE advertisements from devices matching Even R1.
The entire scan has an additional startup/shutdown timeout budget.

Added real Qt thread regression tests for repeated scans, discovered rings,
empty results and Bluetooth errors. 286 automated tests pass.

Live Windows BLE scanning now works with Bluetooth enabled, but no R1-matching
advertisement or real ring gesture notification has been validated on this PC.
No initialization commands, application characteristic writes or DFU operations
were added. Windows controls remain paused on launch.
