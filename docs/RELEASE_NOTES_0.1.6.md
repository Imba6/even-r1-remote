Real R1 gesture reception and touch-source activation

The R1 test connection produced real 11-byte 00 09 61 00 notifications for all
six supported gesture codes. The desktop app now sends the fixed documented
touch-source enable request once after both notification channels subscribe,
including on a new connection after a disconnect.

- Show sensor request progress separately from confirmed gesture reception.
- Preserve raw reception if activation fails; do not treat a write as proof of gestures.
- Keep unknown 09/0A codes in raw history while ignoring them for Windows actions.
- Keep the command-line diagnostic transport passive, with no application writes.
- Add --connect to connect to a saved ring when opening the packet viewer.

Windows controls still start paused. Input-action behavior and compatibility
across firmware versions remain to be verified. No phone-role authentication,
health queries, persistent settings, reset or firmware commands are added.
