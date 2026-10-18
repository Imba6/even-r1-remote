import time
from .protocol import Gesture

class Actions:
    def __init__(self, settings, keyboard=None, mouse=None):
        self.settings = settings
        self.keyboard, self.mouse = keyboard, mouse
        self.enabled = False
        self.last = {}
        self.last_scroll = 0
    @staticmethod
    def parse_hotkey(text):
        from pynput.keyboard import Key
        tokens = text.lower().split("+")
        result = []
        for token in tokens:
            token = token.strip()
            if not token: raise ValueError("Empty key; use 'plus' for the + character")
            token = {"control": "ctrl", "escape": "esc", "plus": "+"}.get(token, token)
            key = getattr(Key, token, None)
            if key is None:
                if len(token) != 1: raise ValueError(f"Unknown key: {token}")
                key = token
            result.append(key)
        if len(result) > 8: raise ValueError("A shortcut supports at most eight keys")
        return result
    def execute(self, gesture, now=None):
        if not self.enabled: return "Paused"
        now = time.monotonic() if now is None else now
        s = self.settings.data
        if now - self.last.get(gesture, -100) < s["debounce_ms"] / 1000: return "Debounced"
        self.last[gesture] = now
        mapping = s["profiles"][s["profile"]][gesture]
        action = mapping["action"]
        if action == "Disabled": return action
        from pynput.keyboard import Controller, Key
        from pynput.mouse import Controller as Mouse, Button
        if self.keyboard is None: self.keyboard = Controller()
        if self.mouse is None: self.mouse = Mouse()
        if action.startswith("Scroll"):
            multiplier = 2 if s["acceleration"] and now - self.last_scroll < .35 else 1
            self.last_scroll = now
            self.mouse.scroll(0, s["scroll_steps"] * multiplier * (1 if action == "Scroll up" else -1))
        elif action.endswith("click"):
            self.mouse.click({"Left click": Button.left, "Right click": Button.right, "Middle click": Button.middle}[action])
        else:
            media = {"Volume up": Key.media_volume_up, "Volume down": Key.media_volume_down,
                     "Play/pause": Key.media_play_pause, "Previous track": Key.media_previous,
                     "Next track": Key.media_next}
            keys = self.parse_hotkey(mapping["hotkey"]) if action == "Keyboard shortcut" else [media[action]]
            pressed = []
            try:
                for key in keys:
                    self.keyboard.press(key)
                    pressed.append(key)
            finally:
                for key in reversed(pressed): self.keyboard.release(key)
        return action
