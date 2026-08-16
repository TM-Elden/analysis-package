from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckContext:
    """Everything a check needs: the package root and its already-parsed manifest.

    Checks never touch YAML themselves - see load_manifest.py.
    """

    package_path: Path
    manifest: dict[str, Any]
