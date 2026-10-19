# v0.1.4 — Complete packet history in the window

New All packets tab gives raw notifications a full-size view without a row limit.
It shows UTC timestamps, source characteristic, exact byte length and hex for
every received packet, including unknowns and duplicates on both channels.
The live view works before, during and after file recording.

Packet count, independent recording indicator, auto-scroll toggle and full-history
search support manual inspection. JSONL import marks historical packets as FILE;
new notifications are marked RX. Export saves the entire displayed history.
The Data capture preview also retains all notifications instead of its former
100-line limit. No BLE protocol commands or decoder assumptions were added.
