Tap then long press

Recognize the observed R1 code 09 / parameter 02 00 as Tap then long press: make
a short tap and hold the second contact. The gesture has its own row in Gesture
mappings and can be assigned any supported action or shortcut.

Existing profile mappings are preserved. The new gesture defaults to Disabled
in every profile. No separate single-tap or long-press event is synthesized for
the combined packet; normal release handling remains available.

Decoding is limited to the observed exact 11-byte form. Other code-09 parameters
and code 0A remain raw notifications without actions. BLE activation is unchanged.
