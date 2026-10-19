"""The single validated RAM touch-source enable request for an existing R1 link.

This fixed request is system 01 / command 00 / touchSwitch 07, request status 00,
serial 0000, payload 02 01. It opens touch source zero without changing stored
settings. There is deliberately no generic command encoder or disable request.

Protocol evidence: evenRealities-openCFW, 5a55562c8a4fb2ac52fa791c0ca7c4e4131e5395,
r1/components/runtime/native_touch_switch.c; compact phone checksum reference at
832137ec/r1/src/r1_protocol.c. The exact request was tested on the owner's R1 on
2026-10-19 and was followed by real 00 09 61 00 gesture notifications. A successful
write-without-response alone does not confirm activation or gesture reception.
"""

TOUCH_ENABLE_UUID = "bae80012-4f05-4503-8e65-3af1f7329d1f"
TOUCH_ENABLE_FRAME = bytes.fromhex("00 B7 84 39 A9 64 01 64 00 00 00 00 07 0E 00 A5 D3 02 01")
