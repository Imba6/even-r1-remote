# v0.1.0 experimental preview

Windows desktop UI, read-only BLE diagnostic transport, Hermes gesture decoder,
configurable profiles/actions, tray controls, startup preferences and build workflow.

Validation: 283 automated tests and source UI smoke passed. Portable executable
startup/exit smoke is checked separately. This is an unsigned Windows x64 build.

Hardware status: the development PC reported Bluetooth POWERED_OFF. No real ring
notifications have been validated. A connected silent ring may need firmware
initialization that this app deliberately does not attempt. Battery is available
only through standard 2A19 when exposed. No G2/cloud dependency or DFU operations.

Download EvenR1Remote.exe for the portable app. The portable zip also includes
license/dependency notices; source is available in the repository and source zip.
See README for pairing, diagnostic capture and hardware acceptance steps.
