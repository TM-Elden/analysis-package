"""Role model (C11 authz scaffold) - data only, not enforced beyond this phase.

Roles match docs/DESIGN-FATHM-SYSTEM.md section C11's suggested minimum set verbatim (no rename
needed): analyst, reviewer, team_reader, company_reader, standard_approver, admin. `admin` is
treated as a bypass everywhere a specific role is checked (see Identity.has_role) rather than a
role callers must additionally hold alongside the others.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    TEAM_READER = "team_reader"
    COMPANY_READER = "company_reader"
    STANDARD_APPROVER = "standard_approver"
    ADMIN = "admin"
