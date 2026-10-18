import json
import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from .protocol import Gesture

ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EvenR1Remote"
ACTIONS = ["Disabled", "Scroll up", "Scroll down", "Volume up", "Volume down",
           "Play/pause", "Previous track", "Next track", "Keyboard shortcut",
           "Left click", "Right click", "Middle click"]

def defaults():
    base = dict(zip(Gesture, ["Play/pause", "Next track", "Disabled", "Disabled", "Scroll down", "Scroll up"]))
    profiles = {}
    for name in ["Default", "Media", "Browser", "Presentation"]:
        profiles[name] = {g: {"action": a, "hotkey": ""} for g, a in base.items()}
    for g, a in [(Gesture.FORWARD, "Volume down"), (Gesture.BACKWARD, "Volume up")]:
        profiles["Media"][g]["action"] = a
    for g, key in [(Gesture.TAP, "enter"), (Gesture.DOUBLE, "alt+left")]:
        profiles["Browser"][g] = {"action": "Keyboard shortcut", "hotkey": key}
    for g, key in [(Gesture.FORWARD, "right"), (Gesture.BACKWARD, "left"), (Gesture.TAP, "f5"), (Gesture.DOUBLE, "esc")]:
        profiles["Presentation"][g] = {"action": "Keyboard shortcut", "hotkey": key}
    return dict(profiles=profiles, profile="Default", address="", auto_connect=False,
                minimize_tray=True, scroll_steps=3, acceleration=False, debounce_ms=180)

class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else ROOT / "settings.json"
        self.data = defaults()
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict):
                    raise ValueError("Settings must be an object")
                for k in ("address", "profile"):
                    if isinstance(saved.get(k), str): self.data[k] = saved[k]
                for k in ("auto_connect", "minimize_tray", "acceleration"):
                    if isinstance(saved.get(k), bool): self.data[k] = saved[k]
                for k, lo, hi in [("scroll_steps", 1, 20), ("debounce_ms", 0, 2000)]:
                    if type(saved.get(k)) is int: self.data[k] = max(lo, min(hi, saved[k]))
                for name, mapping in saved.get("profiles", {}).items():
                    if not isinstance(name, str) or not isinstance(mapping, dict): continue
                    clean = {}
                    for g in Gesture:
                        v = mapping.get(g, {})
                        clean[g] = v if isinstance(v, dict) and v.get("action") in ACTIONS and isinstance(v.get("hotkey"), str) else {"action": "Disabled", "hotkey": ""}
                    self.data["profiles"][name] = clean
                if self.data["profile"] not in self.data["profiles"]: self.data["profile"] = "Default"
            except (ValueError, OSError, AttributeError, TypeError):
                logging.exception("Invalid settings; using safe defaults")
                self.data = defaults()
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp.replace(self.path)

def setup_logging():
    ROOT.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(ROOT / "remote.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[handler])
