"""Persists the last-acknowledged `getUpdates` offset to disk.

Without this, a systemd restart (task requirement 5) would re-fetch and re-answer every message
Telegram hasn't yet had an acknowledged offset for - `getUpdates` only stops redelivering an
update once a later call passes `offset > that update's update_id`. Persisting across restarts is
what makes "restart-on-failure" safe rather than merely alive.
"""

from __future__ import annotations

import json
from pathlib import Path


class OffsetStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> int | None:
        try:
            return json.loads(self.path.read_text())["offset"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def save(self, offset: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"offset": offset}))
