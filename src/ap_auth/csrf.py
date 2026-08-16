"""CSRF token derivation for cookie-authenticated (browser) sessions.

Design doc (`data/fathm-phase3-readiness/report.md` section 5.2): "cheap and adequate for
same-site-only v0". The session cookie is HttpOnly, so no page script - same-site or cross-site -
can read the raw session token to compute a matching CSRF value; a signed derivative of that same
token, handed to the legitimate client once at login and echoed back as a custom header, is a
lightweight double-submit token with no extra server-side storage. Bearer-token (service account)
callers never send this cookie in the first place, so they are exempt - see
`ap_api.deps.identity_from_request`.
"""

from __future__ import annotations

import hashlib
import hmac


def csrf_token_for(raw_session_token: str) -> str:
    return hashlib.sha256(f"csrf:{raw_session_token}".encode("utf-8")).hexdigest()


def csrf_token_matches(raw_session_token: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token_for(raw_session_token), presented)
