# v0.1.3 — Raw data capture and labelled gesture repetitions

New Data capture tab records full BLE notifications to unique local JSONL files.
Records include source UTC and monotonic timestamps, characteristic/handle,
byte length and exact hex, connection IDs and packet sequence. Duplicate and
unknown notifications remain in the capture before decoding or deduplication.
Every record is flushed to disk.

Timed series add a rest baseline, preparation countdown and labelled action/rest
windows for one to ten repetitions. Trial IDs and intended-action labels enable
later comparisons without guessing packet meanings. Delayed UI delivery is
handled using transport timestamps. Manual markers, packet count, live preview,
saved path and folder access are included. Disconnects cancel the active series;
recording may continue through reconnection. Stop or quit finalizes the file.

Windows input stays paused during capture. No protocol initialization, firmware
or DFU writes were added. Actual gesture meanings remain unvalidated.
