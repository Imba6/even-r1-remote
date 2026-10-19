"""Independent offline checks for the only application request the app can send."""
from binascii import crc_hqx

import pytest

from even_r1.gesture_sensor import TOUCH_ENABLE_FRAME, TOUCH_ENABLE_UUID


def outer_checksum(model):
    value = 0
    for octet in model:
        value ^= octet << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x1EDC6F41 if value & 0x80000000 else 0)) & 0xFFFFFFFF
    return value


def compact_checksum(model):
    # Pinned openCFW 832137ec/r1/src/r1_protocol.c: phone_checksum.
    # High serial/length bytes and both checksum bytes are absent here.
    compact = bytes(model[index] for index in (0, 1, 2, 3, 5, 6, 7, 8)) + b"\x00"
    return crc_hqx(compact + model[12:], 0xFFFF)


@pytest.mark.parametrize("hex_value", [
    # Existing com.even.sg TX captures from Hermes ring-frame.test.mjs.
    # These fixtures are NEVER passed to a transport or Bluetooth API.
    "00971953f964016401000000080d003f0101",  # pairAuth OFFLINE ONLY
    "0000045a68640164290000000f0c00015d",    # systemSettingsGet OFFLINE ONLY
    "00d5faceaf640164280000000e0c00912f",    # healthSettingsGet OFFLINE ONLY
])
def test_checksum_algorithms_match_independent_captured_frames(hex_value):
    frame = bytes.fromhex(hex_value)
    model = frame[5:]
    assert outer_checksum(model) == int.from_bytes(frame[1:5], "little")
    assert compact_checksum(model) == int.from_bytes(model[10:12], "little")


def test_only_enable_frame_has_exact_validated_touch_request_shape_and_checksums():
    assert TOUCH_ENABLE_UUID == "bae80012-4f05-4503-8e65-3af1f7329d1f"
    assert type(TOUCH_ENABLE_FRAME) is bytes and len(TOUCH_ENABLE_FRAME) == 19
    assert TOUCH_ENABLE_FRAME == bytes.fromhex("00 B7 84 39 A9 64 01 64 00 00 00 00 07 0E 00 A5 D3 02 01")
    assert TOUCH_ENABLE_FRAME[0] == 0  # Complete, unfragmented model.
    model = TOUCH_ENABLE_FRAME[5:]
    assert model[:3] == bytes.fromhex("64 01 64")
    assert model[3:8] == bytes.fromhex("00 00 00 00 07")  # serial=0, request=0, cmd=0/sub=7
    assert int.from_bytes(model[8:10], "little") == len(model)
    assert model[12:] == bytes.fromhex("02 01")
    assert compact_checksum(model) == 0xD3A5 == int.from_bytes(model[10:12], "little")
    assert outer_checksum(model) == 0xA93984B7 == int.from_bytes(TOUCH_ENABLE_FRAME[1:5], "little")
