"""Shared path-containment helper for every path-bearing check.

Manifest-declared paths come from planner/agent-submitted packages that a
reviewer or CI runner didn't necessarily author. `Path.__truediv__` treats an
absolute right-hand side as an override and silently follows `..` segments,
so a bare `pkg / rel_path` lets a crafted manifest (`inputs[].path:
/etc/passwd` or `../../secrets.txt`) make checks read, hash, or report on
files outside the package directory. Every check that resolves a
manifest-declared path must go through `resolve_contained` instead.
"""

from __future__ import annotations

from pathlib import Path


def resolve_contained(pkg: Path, rel_path: str) -> Path | None:
    """Resolve rel_path under pkg, or return None if it escapes pkg."""
    pkg_resolved = pkg.resolve()
    candidate = (pkg / rel_path).resolve()
    try:
        candidate.relative_to(pkg_resolved)
    except ValueError:
        return None
    return candidate
