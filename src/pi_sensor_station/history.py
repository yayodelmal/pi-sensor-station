"""Small, atomically persisted 24 hour sensor history."""

import json
import os
import tempfile
import time
from pathlib import Path

SAMPLE_SECONDS = 15 * 60
SAMPLE_COUNT = 96


class History:
    def __init__(self, path=None, now=None):
        self.path = Path(path) if path else None
        self.samples = {"temperature": [None] * SAMPLE_COUNT, "humidity": [None] * SAMPLE_COUNT}
        self._buckets = {"temperature": [], "humidity": []}
        self.last_slot = None
        self.last_flush = 0.0
        self.load(now)

    def load(self, now=None):
        if not self.path or not self.path.exists():
            return
        now = time.time() if now is None else now
        try:
            data = json.loads(self.path.read_text())
            items = data.get("samples", {})
            saved_at = float(data.get("saved_at", now))
            for name in self.samples:
                values = items.get(name, [])
                if not isinstance(values, list):
                    continue
                first = saved_at - (len(values) - 1) * SAMPLE_SECONDS
                restored = [v if isinstance(v, (int, float)) and now - (first + i * SAMPLE_SECONDS) <= 86400 else None
                           for i, v in enumerate(values[-SAMPLE_COUNT:])]
                self.samples[name] = ([None] * (SAMPLE_COUNT - len(restored)) + restored)[-SAMPLE_COUNT:]
        except (OSError, ValueError, TypeError, KeyError):
            self.samples = {"temperature": [None] * SAMPLE_COUNT, "humidity": [None] * SAMPLE_COUNT}

    def update(self, readings, timestamp=None):
        timestamp = time.time() if timestamp is None else timestamp
        slot = int(timestamp // SAMPLE_SECONDS)
        if self.last_slot is None:
            self.last_slot = slot
            return False
        changed = False
        if slot > self.last_slot:
            elapsed = slot - self.last_slot
            for name in self.samples:
                values = self._buckets[name]
                self.samples[name].append(sum(values) / len(values) if values else None)
                self.samples[name].extend([None] * max(0, elapsed - 1))
                self.samples[name] = self.samples[name][-SAMPLE_COUNT:]
                self._buckets[name] = []
            self.last_slot, changed = slot, True
        for name in self.samples:
            v = readings.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                self._buckets[name].append(float(v))
        return changed

    def flush_if_due(self, interval=60, force=False):
        if not self.path or (not force and time.monotonic() - self.last_flush < interval):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {"samples": {name: values[-SAMPLE_COUNT:] for name, values in self.samples.items()},
                   "saved_at": now}
        fd, temp = tempfile.mkstemp(prefix=self.path.name + ".", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.last_flush = time.monotonic()
