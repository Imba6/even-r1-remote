# v0.1.2 — Preserve discovered ring and available notification channels

Pass the real selected BLEDevice into connection setup instead of requiring a
second successful scan before connecting. A failed subscription no longer tears
down another working channel. Diagnostics records the actual active channels.
Saved addresses missing from a new scan can use a verified ring identity already
known to Windows; an actual connection is still required and separately checked.

Live evidence on one R1/Windows 11 PC: discovery succeeded after attaching the
motherboard antenna; GATT enumeration returned the expected BAE80001 service;
BAE80011 notifications worked before pairing, while BAE80013 required standard
Windows Bluetooth pairing. Both subscriptions succeeded after pairing.

Actual raw notifications were captured during user gesture attempts, but their
shapes do not match the known Hermes gesture formats. No ring gesture-to-Windows
action success is claimed. Unknown packets remain unassigned. No application
characteristic writes, initialization commands or DFU operations were added.
