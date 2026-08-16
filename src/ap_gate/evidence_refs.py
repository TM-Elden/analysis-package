"""evidence_refs fragment syntax (P3): optional '#rows=col:val[,col:val...]' suffix on
an evidence_refs entry, pointing at a specific slice of an input file instead of the
whole file (e.g. 'inputs/supplier_splits.csv#rows=part:BBU-100'). Documented in
STANDARD.md next to the normative override-row example.

SHOULD, never MUST: plain whole-file refs (no fragment) and external_ref URIs
(contracts://...) remain valid and parse to an empty row_filters. Not enforced by any
gate check - this is a shared best-effort parser so a future exporter (or a stricter
check) doesn't hand-roll fragment parsing per call site; a malformed fragment degrades
to "no filter" rather than raising, matching evidence_refs' free-text nature elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRAGMENT_RE = re.compile(r"^rows=(?P<filters>.+)$")


@dataclass
class EvidenceRef:
    path: str
    row_filters: dict[str, str] = field(default_factory=dict)

    @property
    def has_fragment(self) -> bool:
        return bool(self.row_filters)


def parse_evidence_ref(ref: str) -> EvidenceRef:
    """Split an evidence_refs entry into its base path/URI and optional row filters."""
    if "#" not in ref:
        return EvidenceRef(path=ref)
    path, _, fragment = ref.partition("#")
    match = _FRAGMENT_RE.match(fragment)
    if not match:
        return EvidenceRef(path=path)
    filters: dict[str, str] = {}
    for pair in match.group("filters").split(","):
        col, sep, val = pair.partition(":")
        if sep and col:
            filters[col] = val
    return EvidenceRef(path=path, row_filters=filters)
