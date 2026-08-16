from __future__ import annotations

import json
from typing import Any


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=False)
