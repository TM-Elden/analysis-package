"""C20 planner chat v0 (design doc section 13k; readiness report section 5.5).

Package layout deliberately keeps two things apart:

- **This package's top level** (`core.py`, `identity_map.py`, `manager_client.py`,
  `formatting.py`, `runner.py`) is platform-neutral: an `IncomingMessage` / `OutgoingReply` shape,
  an allowlist-based identity mapping, a `POST /chat/manager` HTTP client, citation-link
  formatting, and a reconnect/backoff polling loop skeleton (`BotRunner`) that drives any
  `ChatPlatform` implementation.
- **`ap_chat.telegram`** is the only platform adapter today (captain-decided: Telegram for v0,
  not Slack - `fm-decision-hold.sh id fathm-phase3-readiness chat-platform`). It implements
  `ChatPlatform` against the Telegram Bot API via long-polling `getUpdates` (outbound-only, no
  public HTTPS endpoint needed - see `telegram/client.py`).

Adding Slack later means writing `ap_chat/slack/` with its own `ChatPlatform` implementation and a
new entrypoint - nothing in `core.py`/`identity_map.py`/`manager_client.py`/`formatting.py`/
`runner.py` is Telegram-shaped, so none of it should need to change. See CLAUDE.md's "Phase 3" /
C20 section (once added there) for the durable summary.
"""

from __future__ import annotations
