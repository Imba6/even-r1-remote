# Even R1 Remote

Independent Windows 11 desktop remote for the Even Realities R1. Direct BLE,
local settings, no G2 dependency, no cloud and no firmware changes.

**Experimental: real R1 gesture reception has been observed on one ring.**
Windows discovery, pairing, both notification subscriptions and all seven supported
gesture types have been captured. The desktop app sends one fixed, documented
touch-sensor enable request after subscribing. Windows input actions and broad
firmware compatibility still require validation; controls start paused.

Version 0.1.1 fixes an unresponsive Scan button caused by a Qt worker signal
collision. Diagnostics now reports both all BLE devices seen and R1 matches.
Version 0.1.2 preserves a selected discovered device through connection setup and
keeps available notification channels active if another channel is protected.
Version 0.1.3 adds raw capture sessions with labelled, timed repetitions.
Version 0.1.4 adds an All packets tab with the complete notification history.
Version 0.1.5 adds receive health and manual subscription refresh.
Version 0.1.6 enables the ring's touch source once after each connection.
Version 0.1.7 recognizes tap then long press as a separate configurable gesture.

![Desktop](docs/desktop.png)

## Install and connect

Download the portable Windows x64 exe from Releases, or the
EvenR1Remote-Windows-x64 artifact from a successful Actions run. Extract archives
and run EvenR1Remote.exe. Python is not needed. This initial build is unsigned.

1. Enable Windows Bluetooth, wake/charge the ring, and release other central
   connections (phone, glasses or another application).
2. Scan, select your advertised Even R1 and connect. The app subscribes to both
   channels and sends the touch-sensor enable request once for this connection.
3. Keep Windows controls paused. Open Diagnostics and perform every gesture.
   Check actual notification bytes and decoded events before enabling controls.
4. Choose a profile, configure mappings and enable Windows controls. Actions
   affect the foreground application. Pause from the tray or main window.

Follow Windows pairing prompts if presented. Manual pairing is available through
Settings > Bluetooth & devices > Add device. First-time provisioning and fresh
ring compatibility are unverified. The official app is not required at runtime.
The app distinguishes waiting for the first packet from receiving packets.
The sensor indicator confirms actual gesture reception only after decoding a
real gesture packet. Successful submission of the enable request alone does
not establish reception.

## Features

- Two supported notification channels, touch-source activation, GATT enumeration,
  raw packet diagnostics.
- Single/double tap, long press/release, forward/backward swipe, tap then long press.
- Scroll, optional acceleration, volume/media, mouse clicks, custom shortcuts.
- Default, Media, Browser, Presentation and duplicate-to-custom profiles.
- Auto-connect to a saved ring, reconnect backoff, tray pause and minimize.
- Optional current-user Windows startup registration; controls start paused.
- Standard battery reads when available. RSSI is explicitly the last scan value.

## Record data for gesture research

For visual inspection, open **All packets**. It shows every received notification
from both subscribed channels, including unknown and duplicate packets, even when
file recording is off. No old rows are discarded during the current app run.
Turn off **Auto-scroll** to inspect earlier data; **Find next** searches the full
history without filtering it. **Load JSONL** loads earlier notifications, marked
FILE, while incoming live notifications are marked RX. **Export all text** saves
the entire displayed history. The recording indicator independently shows whether
new live data is being saved to a capture file.

The viewer separates imported FILE and live RX totals. Current connection status
shows the number of active subscriptions, received packets and time since the
last real notification. A successful subscription with no data is explicitly
shown as waiting for the first packet. **Refresh subscriptions** re-subscribes
the active notification channels using standard CCCD operations. It sends no
application commands. Windows connections discover fresh services, and intentional
disconnects disable active subscriptions before closing the connection.
Refresh does not repeatedly send the touch-source enable request.

**Tap then long press** is a separate mapping: make a short tap, then hold the
second contact for about one second. The observed packet uses code 09 with
parameter bytes 02 00. Its action defaults to Disabled in all profiles; select
an action under Gesture mappings. It is not synthesized from separate single
tap and long-press actions. Other code-09 parameters and code 0A remain unknown.

Connect the selected ring (a saved ring can be selected before scanning), then
open **Data capture**. Press **Start recording** to
create a new local JSONL file. Windows controls are paused and disabled while
recording. The displayed path is saved immediately; every record is flushed to
disk, independently of the live display.

Select an action, leave the default five repetitions, and press **Run selected
action**. Remain still during the initial five-second baseline. Each repetition
has a three-second countdown, a five-second action window, and three seconds of
rest. Perform the selected gesture **once** during each **DO ONCE** window. Then
select another action and run its series in the same recording. Custom action
labels and optional manual markers are supported. A disconnect cancels the
current series; logging continues through reconnects until **Stop & save**.

Captures live in `%LOCALAPPDATA%\EvenR1Remote\captures`. **Open capture folder**
opens that location. Session files contain exact notification hex, length,
characteristic UUID, optional handle, connection/sequence identifiers, UTC time
and a monotonic clock timestamp. Duplicates and unknown packets are retained
before decoding or debounce. Trial boundaries carry the intended action label,
repetition and trial ID. Notifications are attributed using their source timestamp,
even when UI delivery is delayed. Labels do not establish a packet's meaning.

Files stay on this PC and are not uploaded. Recording adds no commands and does
not query health data. The desktop connection sends only the fixed touch-source
enable request; all raw notifications the ring sends remain visible.

## Development and packaging

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m even_r1
python -m pytest -q
python tests/ui_smoke.py
```

Passive diagnostics, with no application writes or Windows input simulation:

```powershell
python -m even_r1.diagnostics
python -m even_r1.diagnostics --address AA:BB:CC:DD:EE:FF --seconds 60
python -m even_r1.diagnostics --address AA:BB:CC:DD:EE:FF --seconds 60 --record --label "single tap"
```

The CLI intentionally does not activate the touch sensor. Use the desktop app
for the connection and activation flow. To open directly on the packet viewer
and connect to the saved ring, use `EvenR1Remote.exe --live-packets --connect`.

Build a portable exe:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name EvenR1Remote --collect-submodules bleak.backends.winrt --collect-submodules pynput --copy-metadata bleak --add-data "LICENSE;." launch.py
```

Output: dist/EvenR1Remote.exe. Actions tests and builds with Python 3.12 on Windows.
ble.py owns transport, protocol.py pure decoding, actions.py input/debounce,
settings.py profiles/persistence, startup.py Run registration and ui.py Qt UI.

## Troubleshooting

- Bluetooth powered off: enable the radio and retry scanning. Wake the ring,
  move closer and disconnect competing applications if no advertisement appears.
- Connected but silent: check the sensor indicator and Diagnostics for the
  touch-source request, subscription errors and live RX count. Release other
  central connections, take the ring off its charger and wear it for gestures.
  Unknown packets remain raw data and are not assigned gesture meanings.
- A notification channel requires authentication: pair the selected R1 in Windows
  Bluetooth settings. In the observed test, standard Windows pairing enabled
  access to BAE80013. Available channels stay active if another subscription fails.
- Battery unavailable: standard 2A19 may be absent. Proprietary health is not queried.
- Swipe direction: swap mappings if desired; charger up maps to backward and
  down to forward to preserve Hermes event semantics.
- Rapid duplicate actions: adjust debounce. Charger gesture/tick pairs are
  suppressed within the current session.
- Input does nothing: check controls enabled, selected profile and foreground
  window. Windows privilege boundaries can prevent input into elevated apps.
- Close hides the app: reopen from the tray; choose Quit to disconnect and exit.
- Startup needs the registered exe/source environment to stay at its original path.

Settings and rotating logs live in `%LOCALAPPDATA%\EvenR1Remote`. Logs include
device identifiers and raw notification bytes. Unsolicited packets might include
data beyond gestures; health values are never requested, parsed or uploaded.
Review exports before sharing. Disable startup, quit and remove that folder to reset.

See [research and hardware checks](docs/RESEARCH.md), [license](LICENSE), and
[third-party attribution](THIRD_PARTY.md). Unaffiliated with Even Realities.
