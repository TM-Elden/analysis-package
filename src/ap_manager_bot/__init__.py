"""C4 manager bot: the shared, per-caller-scoped Q&A backend both the manager console and planner
chat front (`POST /chat/manager` - see `ap_api.chat_routes`). See CLAUDE.md's "Phase 3: C4 manager
bot" section for the architecture (tool-loop shape, scoping double-check, citation contract).
"""

from __future__ import annotations
