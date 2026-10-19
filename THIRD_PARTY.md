# Third-party attribution

The gesture decoder is a Python port of FaceclawRingEventDecoder.java from
not-benny/hermes-g2, revision b1e167ba6eff779c3ff3259f253c035316c52b3a.
Original attribution belongs to Hermes G2 / Faceclaw contributors. The upstream
project is GPL-3.0; this derivative is distributed under GPL-3.0-or-later.
https://github.com/not-benny/hermes-g2

The tap-then-long-press extension (11-byte code 09, parameter 02 00) is based on
the owner's local R1 observations and repetitions, alongside Even's public
description of the combined gesture. It is not present in the pinned Hermes
decoder.
https://support.evenrealities.com/hc/en-us/articles/14269160297999-Menu

The fixed touch-source enable request and protocol layout were independently
implemented from public reverse-engineering facts in evenRealities-openCFW,
revision 5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395 (touch handler, RAM source
manager and gesture dispatcher) and revision 832137ec (compact phone checksum).
No firmware binaries or reconstructed firmware implementation are bundled.
https://github.com/kalanihelekunihi/evenRealities-openCFW

Runtime components include Bleak (MIT), pynput (LGPL-3.0), PySide6/Qt
(LGPL-3.0/GPL/commercial), Python (PSF) and WinRT Python bindings (MIT).
PyInstaller provides an application bundling exception. Dependency license files
are included with the release notices; exact versions are in requirements-lock.txt.
To replace Qt libraries, rebuild from source with your compatible PySide6 version
using the README build instructions.

Public visual/feature reference only; no code or assets copied:
https://www.reddit.com/r/EvenRealities/comments/1x8abds/i_got_the_even_r1_working_as_a_standalone_windows/
The author states their code remains local. Background only, no code dependency:
https://github.com/Imba6/soniox-translate
