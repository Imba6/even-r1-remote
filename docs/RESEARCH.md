# Research and hardware acceptance

Research date: 2026-10-19. Hermes revision:
b1e167ba6eff779c3ff3259f253c035316c52b3a.
Reviewed FaceclawRingEventDecoder.java, BleManager connection/notification paths,
BleCommunicator ring paths, ring-wire-format-2026-08-20.md and ring-related tests.
https://github.com/not-benny/hermes-g2

The wire-format note describes health transport, which is not needed here.
Communicator session/probe commands are not ported. No application writes are
implemented. Notification subscriptions necessarily perform CCCD operations
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
