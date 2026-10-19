# Research and hardware acceptance

Research date: 2026-10-19. Hermes revision:
b1e167ba6eff779c3ff3259f253c035316c52b3a.
Reviewed FaceclawRingEventDecoder.java, BleManager connection/notification paths,
BleCommunicator ring paths, ring-wire-format-2026-08-20.md and ring-related tests.
https://github.com/not-benny/hermes-g2

The wire-format note describes health transport, which is not needed here.
Communicator session/probe commands are not ported. Initially no application writes
were implemented; see the validated touch-source request below. Subscriptions perform CCCD operations
internally through Bleak. FE59 is only enumerated; no DFU operations occur.

Direct packets are exactly three bytes: FF0401 tap, FF0402 double, FF0320 hold.
FF05 parameters 0/1 forward; 2..255 backward. Charger packets are exactly eleven
bytes: 00096100, code, u16 little-endian parameter, u32 little-endian tick.
Codes 0 hold, 1 tap, 2 double, 4 up/backward, 5 down/forward, 8 release.
Unknown shapes are logged and ignored. No speculative packet reassembly.

The Reddit post and comments describe scrolling, media, shortcuts, presentation,
mappings and experimental automatic profiles. Its code remains private. The
preview link redirected to the post; exact screenshot fidelity is unverified.
The app uses an original dark green card layout and original ring drawing.
https://www.reddit.com/r/EvenRealities/comments/1x8abds/i_got_the_even_r1_working_as_a_standalone_windows/

The soniox-translate README describes a G2/Soniox web translation stack; this
application has no integration or cloud dependency on it.
https://github.com/Imba6/soniox-translate
Bleak API: https://bleak.readthedocs.io/en/latest/api/client.html

## Outstanding hardware checks

Windows diagnostic discovery returned POWERED_OFF. No actual ring notifications,
battery reads or reconnect behavior were validated. Unit fixtures are synthetic
and never appear as fake UI telemetry. With Bluetooth enabled, capture GATT and
every real gesture several times, verify swipe direction and hold release, idle
behavior, out-of-range reconnect, manual disconnect and foreground input actions.
A connected but silent ring remains unsupported until passive-compatible firmware
or a safe documented initialization sequence is established.

## Subsequent Windows hardware observations (2026-10-19)

After connecting the motherboard antenna, Windows discovery saw 17 BLE devices
including the named R1 with advertisement RSSI -69 dBm. A subsequent scan missed
the ring, but lookup by its already observed address in the Windows cache and an
uncached GATT service query both succeeded. Connection therefore must not depend
on a second advertisement after selection.

BAE80011 subscription succeeded without pairing. BAE80013 required authentication;
standard Windows pairing succeeded, after which both subscriptions succeeded.
Raw notifications during user gesture attempts included shapes 00 09 8C 00 xx,
00 09 8B 00 xx xx and 00 1A 89 01 01 00 00. Their semantics remain unverified;
they are not reclassified as gestures. No known FF or 00 09 61 00 gesture packets
were captured. Hardware gesture control remains unvalidated.

## Receive silence and touch-source research (2026-10-19)

After later successful subscriptions, a separate receive probe attached both
Bleak and direct WinRT ValueChanged handlers. Both channel CCCD reads returned
success / NOTIFY before and after subscription, but a 45-second gesture attempt
produced no notifications in either handler. A separate real QThread/UI check
confirmed delivery from the raw notification callback into the packet viewer.
This distinguishes receive silence from an interface filtering problem.

The viewer now separates imported FILE history from live RX and current
connection counts. Transport discovers uncached Windows services, explicitly
stops active notifications before intentional disconnect, and supports bounded
manual CCCD refresh. These changes do not establish gesture compatibility.

Additional primary reverse-engineering evidence identifies the touch source as
separate from notification subscription. Stock 2.2.6.0009 system command
1:00:07 (`touchSwitch`) with the exact two-byte payload `02 01` opens RAM touch
source zero. Selector one is diagnostic only. The reconstructed handler and
source manager show no persistent identity, flash, health or firmware operation.
The acknowledgement precedes the source operation and cannot prove activation.
Subscribing channel one assigns the glasses role; phone-role authentication on
that same link must not be added as a generic initialization step.

Sources:
- [Protocol surface](https://github.com/kalanihelekunihi/evenRealities-openCFW/blob/5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395/r1/docs/protocol.md)
- [Recovered touch-switch handler](https://github.com/kalanihelekunihi/evenRealities-openCFW/blob/5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395/r1/components/runtime/native_touch_switch.c)
- [RAM touch-source manager](https://github.com/kalanihelekunihi/evenRealities-openCFW/blob/5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395/r1/components/runtime/native_touch_services.c)
- [Role assignment](https://github.com/kalanihelekunihi/evenRealities-openCFW/blob/5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395/r1/docs/correlation/CONNECTION-ROLE-ASSIGNMENT-CORRELATION.md)

An exact touch-only encoder was checked offline against captured first-party
CRC vectors before a local hardware experiment. Private capture data and
experimental hardware launchers stay outside the public repository.

## Observed gesture reception and production activation (2026-10-19)

The local experiment submitted exactly one 19-byte touchSwitch request, then
received real eleven-byte `00 09 61 00` notifications. The ring later produced
all supported codes: long press, single tap, double tap, both swipe directions
and release. First gesture reception was about an hour after the request, so
the timestamp alone does not establish immediate activation or its necessity
on every firmware. This confirms the actual packet format on this ring and
supports the documented activation path; it does not validate Windows actions.

Version 0.1.6 submits only that fixed request to BAE80012, without response,
once per connection and after both notification subscriptions. It does not
send phone-role authentication, health, persistent settings, reset or firmware
commands. Subscription refresh does not resend activation. An unavailable or
failed write preserves raw reception and produces an explicit sensor state.
The CLI remains passive with application activation disabled.

Unknown eleven-byte codes 09 and 0A were also observed; 0A remains ignored for
actions, while the later bounded 09 extension is documented below. The original
supported decoder matches Hermes. Its combined parameter
field preserves the two wire bytes; firmware reconstruction calls them distance
and velocity. Actions do not depend on that combined value.

## Tap then long press extension (2026-10-19)

The owner identified code 09 as tap then long press in the official application
and repeated the requested combination. Observed eleven-byte packets consistently
use `00 09 61 00 09 02 00`, following two 0A notifications and preceding an 08
release. Firmware tick spacing distinguishes the held second contact from an
ordinary double tap. The earlier logs contain no synchronized per-trial labels,
so no exact three-for-three trial count is inferred from them.

Even's [Menu guide](https://support.evenrealities.com/hc/en-us/articles/14269160297999-Menu)
documents a short tap followed by holding the second contact for one second for
firmware 2.2.9 or later. The [control guide](https://support.evenrealities.com/hc/en-us/articles/13772400722063-How-to-Control)
also lists this combination. These sources establish the gesture's existence;
they do not define its BLE code. The code mapping is based on the owner's report
and the matching local notifications.

Version 0.1.7 recognizes only code 09 with exact parameter 02 00 in the known
eleven-byte frame. It emits one Tap then long press event rather than inventing
separate tap/hold events. Generic release handling is unchanged. Other 09
parameters and 0A remain ignored for actions. Existing profiles retain their
mappings; this new gesture defaults to Disabled.
