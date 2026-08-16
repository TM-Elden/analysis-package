"""Manager console: the phase-3 server-rendered HTML layer (P3.4 in
`data/fathm-phase3-readiness/report.md` section 6, in the firstmate repo).

`ap_console` renders; `ap_api` stays the format-neutral JSON layer - see CLAUDE.md's "Phase 3
console" section for the module boundary this package exists to preserve. `include_console(app)`
is the single entry point `ap_api.app` calls to mount everything here (routes + static htmx file +
the auth-redirect exception handler).
"""

from __future__ import annotations

from ap_console.routes import include_console

__all__ = ["include_console"]
