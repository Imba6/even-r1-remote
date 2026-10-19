"""Hermes gesture semantics plus a locally observed R1 tap-then-hold extension.

The original decoder is GPL-3.0; see THIRD_PARTY.md. The bounded 09/0200
extension follows the owner's gesture report and matching physical repetitions.
"""
from dataclasses import dataclass
from enum import StrEnum

class Gesture(StrEnum):
    TAP = "Single tap"
    DOUBLE = "Double tap"
    HOLD = "Long press"
    RELEASE = "Long press release"
    FORWARD = "Swipe forward"
    BACKWARD = "Swipe backward"
    TAP_HOLD = "Tap then long press"

@dataclass(frozen=True)
class Event:
    gesture: Gesture
    variant: str
    parameter: int
    tick: int | None = None

def decode(raw: bytes) -> Event | None:
    if len(raw) == 3 and raw[0] == 0xff:
        kind, param = raw[1:]
        gesture = {(3, 32): Gesture.HOLD, (4, 1): Gesture.TAP,
                   (4, 2): Gesture.DOUBLE}.get((kind, param))
        if kind == 5:
            gesture = Gesture.FORWARD if param <= 1 else Gesture.BACKWARD
        return Event(gesture, "direct", param) if gesture else None
    if len(raw) == 11 and raw[:4] == b"\x00\x09\x61\x00":
        gesture = {0: Gesture.HOLD, 1: Gesture.TAP, 2: Gesture.DOUBLE,
                   4: Gesture.BACKWARD, 5: Gesture.FORWARD,
                   8: Gesture.RELEASE}.get(raw[4])
        if raw[4] == 9 and raw[5:7] == b"\x02\x00":
            gesture = Gesture.TAP_HOLD
        if gesture:
            return Event(gesture, "charger", int.from_bytes(raw[5:7], "little"),
                         int.from_bytes(raw[7:11], "little"))
    return None
