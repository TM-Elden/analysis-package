"""Secret detection: the C14 detector pass over a package's raw text content.

Regex set for known key formats (13e's own list: AWS, GitHub, PEM headers, JWT-shaped, emails,
SSN-like patterns) plus a Shannon-entropy check on long tokens for anything the named patterns
miss. Every finding here is `severity="high"` - `redact.redact_package` fails the whole package
closed (not indexed) on any hit; there is no "warn and index anyway" tier today (13e's fail-or-warn
knob, default fail - see the report). A profile's `redaction.json` `disabled_detectors` list is the
tuning valve for false positives (e.g. a commodity class whose part numbers trip the entropy
check), not a severity downgrade.

The entropy detector deliberately skips pure-hex tokens: `content_sha256` hashes are exactly the
kind of long, high-entropy-looking token this package format is full of by design (see
MANIFEST.yaml `inputs[].content_sha256`), and they are not secrets.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Known key/token formats. Every one of these is high severity - see module docstring.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "pem_private_key_header": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "jwt_shaped": re.compile(r"\bey[A-Za-z0-9_-]{10,}\.ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

_ENTROPY_DETECTOR = "high_entropy_token"
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/_=-]{32,}")
_HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")
# bits/char, min length 32: a 64-char hex sha256 lands ~3.9, a path-shaped business-content ref
# (e.g. a `contracts://...` external_ref) lands ~4.3-4.4, a real random 32-byte urlsafe token
# lands ~4.7-5.0. 4.6 sits above the former, below the latter.
_ENTROPY_THRESHOLD = 4.6

# Files that are binary or otherwise never worth text-scanning.
_SKIP_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".pyc"})


@dataclass(frozen=True)
class SecretFinding:
    detector: str
    severity: str  # always "high" today; kept as a field for a future warn tier
    location: str  # package-relative path, e.g. "labels/overrides.jsonl"
    snippet: str  # masked preview - never the full matched secret

    def to_dict(self) -> dict[str, str]:
        return {"detector": self.detector, "severity": self.severity, "location": self.location, "snippet": self.snippet}


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}…{s[-2:]} ({len(s)} chars)"


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def scan_text(text: str, *, location: str, disabled_detectors: frozenset[str] = frozenset()) -> list[SecretFinding]:
    """Scan one blob of text for secret-shaped content. `location` is a human-facing pointer
    (file path, or file path + row id) for the redaction report - never included in what gets
    indexed."""
    findings: list[SecretFinding] = []
    for name, pattern in _PATTERNS.items():
        if name in disabled_detectors:
            continue
        for match in pattern.finditer(text):
            findings.append(SecretFinding(detector=name, severity="high", location=location, snippet=_mask(match.group(0))))
    if _ENTROPY_DETECTOR not in disabled_detectors:
        for match in _ENTROPY_TOKEN.finditer(text):
            token = match.group(0)
            if _HEX_ONLY.match(token):
                continue
            if _shannon_entropy(token) >= _ENTROPY_THRESHOLD:
                findings.append(
                    SecretFinding(detector=_ENTROPY_DETECTOR, severity="high", location=location, snippet=_mask(token))
                )
    return findings


def _is_probably_text(path) -> bool:
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return False
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def scan_package_tree(package_dir, *, disabled_detectors: frozenset[str] = frozenset()) -> list[SecretFinding]:
    """Walk every text file under `package_dir` and scan it. Covers 13e's stated risk surface
    (`code/`, `repro.environment`, input CSVs, `reason_text`) uniformly by scanning the whole
    package tree rather than hand-picking fields - MANIFEST.yaml and every labels/*.jsonl row are
    included too, since a secret could land in any free-text field."""
    findings: list[SecretFinding] = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or not _is_probably_text(path):
            continue
        rel = path.relative_to(package_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        findings.extend(scan_text(text, location=rel, disabled_detectors=disabled_detectors))
    return findings
