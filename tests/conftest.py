from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXAMPLE_PACKAGE = REPO_ROOT / "examples" / "commodity-commit-v1"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
