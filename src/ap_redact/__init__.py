"""ap_redact: the C14 redaction pipeline - `package dir -> redacted chunk stream + redaction report`.

See `redact.redact_package` for the entry point. `ap_index` consumes only this module's `Chunk`
output, never raw package content - see CLAUDE.md.
"""

from __future__ import annotations

from ap_redact.chunk import Chunk
from ap_redact.redact import redact_package
from ap_redact.report import RedactionReport, read_report, write_report

__all__ = ["Chunk", "RedactionReport", "read_report", "redact_package", "write_report"]
