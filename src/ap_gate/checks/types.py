"""Shared types for checks and the layered gate report.

Report layering (second review sections 5.2 and 7.2): a CheckOutcome splits
cleanly into a content-free part (check_id, result, severity, waived) and a
human-facing evidence part (message, paths). The content-free part is what
ends up in the report's `results[]` layer - the layer a future telemetry /
pooled-conformance pipeline can consume without parsing or scrubbing free
text, and the layer that must never carry a person identifier (`author`,
`owners.*`) so gate statistics stay package-level, never person-level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_SKIP = "skip"

SEVERITY_REQUIRED = "required"  # a fail here blocks overall pass
SEVERITY_ADVISORY = "advisory"  # a fail here is informational only (unused by any L1 check today; reserved for future L2-style flag-not-block checks)


@dataclass
class CheckOutcome:
    check_id: str
    result: str  # RESULT_PASS | RESULT_FAIL | RESULT_SKIP
    severity: str = SEVERITY_REQUIRED
    waived: bool = False
    message: str = ""  # planner-facing: which path/field, how to fix. Evidence layer only.
    paths: list[str] = field(default_factory=list)  # evidence layer only.

    def blocks_overall_pass(self) -> bool:
        return self.result == RESULT_FAIL and self.severity == SEVERITY_REQUIRED and not self.waived

    def to_result_row(self) -> dict:
        """The content-free results[] row. Never add paths/messages/identifiers here."""
        return {
            "check_id": self.check_id,
            "result": self.result,
            "severity": self.severity,
            "waived": self.waived,
        }

    def to_evidence_row(self) -> dict:
        """The human-facing evidence row. Paths and messages live only here."""
        row: dict = {"check_id": self.check_id, "message": self.message}
        if self.paths:
            row["paths"] = self.paths
        return row

    @classmethod
    def ok(cls, check_id: str, message: str = "", paths: list[str] | None = None) -> "CheckOutcome":
        return cls(check_id=check_id, result=RESULT_PASS, message=message, paths=paths or [])

    @classmethod
    def fail(cls, check_id: str, message: str, paths: list[str] | None = None) -> "CheckOutcome":
        return cls(check_id=check_id, result=RESULT_FAIL, message=message, paths=paths or [])

    @classmethod
    def advisory_fail(cls, check_id: str, message: str, paths: list[str] | None = None) -> "CheckOutcome":
        """A fail that flags but never blocks overall pass (severity advisory - see blocks_overall_pass).

        For checks like `agent_draft_present` where a profile may later escalate the same
        condition to `required` via `CheckOutcome.fail` instead - the check function decides
        which classmethod to call based on the profile's opt-in flag, not this dataclass.
        """
        return cls(check_id=check_id, result=RESULT_FAIL, severity=SEVERITY_ADVISORY, message=message, paths=paths or [])

    @classmethod
    def skip(cls, check_id: str, message: str = "") -> "CheckOutcome":
        return cls(check_id=check_id, result=RESULT_SKIP, message=message)
