"""Durable, passive capture of BLE notifications and annotated trials."""
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import perf_counter_ns
from uuid import uuid4

from .settings import ROOT


class CaptureSession:
    def __init__(self, directory=None, metadata=None):
        self._lock = RLock()
        self._active = False
        self._packet_count = 0
        self._label = self._trial_id = self._repetition = None
        self._trials = []
        directory = Path(directory) if directory is not None else ROOT / "captures"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = directory / f"r1-{stamp}-{uuid4().hex}.jsonl"
        self._file = self.path.open("x", encoding="utf-8", newline="\n")
        self._active = True
        self._write("session_start", {"schema_version": 1, "metadata": metadata or {}})

    @property
    def active(self):
        with self._lock:
            return self._active

    @property
    def packet_count(self):
        with self._lock:
            return self._packet_count

    def _write(self, kind, payload):
        record = dict(payload)
        record["type"] = kind
        record.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat(timespec="microseconds"))
        record.setdefault("monotonic_ns", perf_counter_ns())
        try:
            self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._file.flush()
        except OSError:
            self._active = False
            try:
                self._file.close()
            except OSError:
                pass
            raise

    def _context(self):
        return {key: value for key, value in (
            ("label", self._label), ("trial_id", self._trial_id),
            ("repetition", self._repetition)) if value is not None}

    def _packet_context(self, source_ns):
        if type(source_ns) is not int:
            return self._context()
        for trial in reversed(self._trials):
            if trial["start_ns"] <= source_ns and (trial["end_ns"] is None or source_ns < trial["end_ns"]):
                return trial["context"]
        return {}

    def record_packet(self, packet):
        """Keep every notification, including duplicate and undecodable packets."""
        with self._lock:
            if not self._active:
                return False
            self._write("notification", {**packet, **self._packet_context(packet.get("monotonic_ns"))})
            self._packet_count += 1
            return True

    def marker(self, label, repetition=None, phase="marker"):
        """Mark an instant, or open/close a named trial around notifications."""
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ValueError("A marker label must contain 1–200 characters")
        if phase not in {"marker", "trial_start", "trial_end"}:
            raise ValueError("Unknown marker phase")
        if repetition is not None and (type(repetition) is not int or repetition < 1):
            raise ValueError("Repetition must be a positive integer")
        with self._lock:
            if not self._active:
                return None
            marker_ns = perf_counter_ns()
            if phase in {"trial_start", "trial_end"} and self._trial_id:
                self._trials[-1]["end_ns"] = marker_ns
            if phase == "trial_start":
                self._label, self._trial_id = label.strip(), uuid4().hex
                self._repetition = repetition
                self._trials.append({"start_ns": marker_ns, "end_ns": None, "context": self._context()})
            values = {**self._context(), "label": label.strip(), "phase": phase, "monotonic_ns": marker_ns}
            if repetition is not None:
                values["repetition"] = repetition
            self._write("marker", values)
            trial_id = self._trial_id
            if phase == "trial_end":
                self._label = self._trial_id = self._repetition = None
            return trial_id

    def event(self, kind, value):
        with self._lock:
            if not self._active:
                return False
            self._write("event", {"kind": kind, "value": value, **self._context()})
            return True

    def stop(self, reason="user"):
        with self._lock:
            if not self._active:
                return
            self._write("session_end", {"reason": reason, "packet_count": self._packet_count})
            self._active = False
            self._file.close()
