import json
from types import SimpleNamespace

import pytest

from even_r1.actions import Actions
from even_r1.ble import NOTIFY, Transport
from even_r1.protocol import Gesture, decode
from even_r1.settings import Settings, defaults


def combo_packet(parameter=2, tick=0x12345678):
    return b"\x00\x09\x61\x00\x09" + parameter.to_bytes(2, "little") + tick.to_bytes(4, "little")


def test_tap_then_long_press_preserves_parameter_and_tick():
    event = decode(combo_packet())

    assert event.gesture is Gesture.TAP_HOLD
    assert event.variant == "charger"
    assert event.parameter == 2
    assert event.tick == 0x12345678


@pytest.mark.parametrize("parameter", [0, 1, 3, 0x200, 0xFFFF])
def test_combo_ignores_unverified_parameters(parameter):
    assert decode(combo_packet(parameter)) is None


def test_combo_requires_the_complete_observed_frame():
    packet = combo_packet()
    for length in range(len(packet)):
        assert decode(packet[:length]) is None
    assert decode(packet + b"\x00") is None
    assert decode(b"\x01" + packet[1:]) is None
    assert decode(bytes.fromhex("ff0902")) is None
    assert decode(bytes.fromhex("ff0409")) is None


@pytest.mark.parametrize("code", [3, 6, 7, 10, 255])
def test_combo_parameter_does_not_recognize_other_unknown_codes(code):
    packet = bytearray(combo_packet())
    packet[4] = code

    assert decode(packet) is None


@pytest.mark.parametrize("code, expected", [
    (0, Gesture.HOLD), (1, Gesture.TAP), (2, Gesture.DOUBLE),
    (4, Gesture.BACKWARD), (5, Gesture.FORWARD), (8, Gesture.RELEASE),
])
def test_combo_parameter_preserves_existing_gesture_codes(code, expected):
    packet = bytearray(combo_packet())
    packet[4] = code

    event = decode(packet)
    assert event.gesture is expected
    assert event.parameter == 2


def test_combo_deduplicates_across_channels_but_keeps_every_raw_packet():
    events = []
    transport = Transport(lambda kind, value: events.append((kind, value)))
    channels = [SimpleNamespace(uuid=uuid) for uuid in sorted(NOTIFY)]

    transport.notification(channels[0], combo_packet(tick=71))
    transport.notification(channels[1], combo_packet(tick=71))
    transport.notification(channels[0], combo_packet(tick=72))

    gestures = [event for kind, event in events if kind == "gesture"]
    assert [(event.gesture, event.tick) for event in gestures] == [
        (Gesture.TAP_HOLD, 71), (Gesture.TAP_HOLD, 72),
    ]
    assert sum(kind == "raw_packet" for kind, _ in events) == 3
    assert sum(kind == "packet" for kind, _ in events) == 3


def test_combo_default_is_disabled_without_reordering_existing_gestures():
    assert list(Gesture) == [Gesture.TAP, Gesture.DOUBLE, Gesture.HOLD, Gesture.RELEASE,
                             Gesture.FORWARD, Gesture.BACKWARD, Gesture.TAP_HOLD]
    profiles = defaults()["profiles"]
    for mapping in profiles.values():
        assert mapping[Gesture.TAP_HOLD] == {"action": "Disabled", "hotkey": ""}
    assert {gesture: value["action"] for gesture, value in profiles["Default"].items()} == {
        Gesture.TAP: "Play/pause", Gesture.DOUBLE: "Next track", Gesture.HOLD: "Disabled",
        Gesture.RELEASE: "Disabled", Gesture.FORWARD: "Scroll down",
        Gesture.BACKWARD: "Scroll up", Gesture.TAP_HOLD: "Disabled",
    }


def test_old_settings_keep_all_mappings_and_add_disabled_combo(tmp_path):
    old_gestures = [Gesture.TAP, Gesture.DOUBLE, Gesture.HOLD, Gesture.RELEASE,
                    Gesture.FORWARD, Gesture.BACKWARD]
    old_mapping = {
        gesture: {"action": "Keyboard shortcut", "hotkey": f"ctrl+{index}"}
        for index, gesture in enumerate(old_gestures)
    }
    old_profiles = {name: dict(old_mapping) for name in ["Default", "Media", "Browser", "Presentation", "Custom"]}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"profiles": old_profiles, "profile": "Custom"}), encoding="utf-8")

    settings = Settings(path)

    assert settings.data["profile"] == "Custom"
    for mapping in settings.data["profiles"].values():
        for gesture in old_gestures:
            assert mapping[gesture] == old_mapping[gesture]
        assert mapping[Gesture.TAP_HOLD] == {"action": "Disabled", "hotkey": ""}
    settings.save()
    assert Settings(path).data == settings.data


def test_combo_is_inert_by_default_and_executes_only_an_assigned_action(tmp_path):
    class Input:
        def __init__(self):
            self.events = []

        def press(self, key):
            self.events.append(("press", key))

        def release(self, key):
            self.events.append(("release", key))

    settings = Settings(tmp_path / "settings.json")
    keyboard, mouse = Input(), Input()
    actions = Actions(settings, keyboard, mouse)
    assert actions.execute(Gesture.TAP_HOLD, now=1) == "Paused"
    actions.enabled = True
    assert actions.execute(Gesture.TAP_HOLD, now=1) == "Disabled"
    assert keyboard.events == [] and mouse.events == []

    settings.data["profiles"]["Default"][Gesture.TAP_HOLD] = {
        "action": "Keyboard shortcut", "hotkey": "ctrl+a",
    }
    assert actions.execute(Gesture.TAP_HOLD, now=2) == "Keyboard shortcut"
    assert [kind for kind, _ in keyboard.events] == ["press", "press", "release", "release"]
    pressed = [key for kind, key in keyboard.events if kind == "press"]
    released = [key for kind, key in keyboard.events if kind == "release"]
    assert released == list(reversed(pressed))
    assert mouse.events == []
    assert actions.execute(Gesture.TAP_HOLD, now=2.01) == "Debounced"
