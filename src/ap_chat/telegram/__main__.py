"""Run the Telegram planner-chat bot: `PYTHONPATH=src python3 -m ap_chat.telegram` (or the
`fathm-chat-telegram` console script). See `docs/telegram-bot-setup.md` for BotFather registration,
`ap-auth` service-account provisioning, allowlist file format, and the systemd unit
(`deploy/systemd/fathm-chat-telegram.service`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# httpx read-timeout margin above `AP_CHAT_POLL_TIMEOUT` (Telegram's own long-poll wait): the
# request round-trip needs slack beyond the server-side wait itself, or a `getUpdates` response
# that lands right at the poll timeout would still read as an httpx timeout.
_POLL_HTTP_TIMEOUT_MARGIN_SECONDS = 10.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Imports deferred past logging.basicConfig so early import-time errors (e.g. a missing
    # TELEGRAM_BOT_TOKEN) still land in the configured log format, not bare stderr.
    from ap_chat.identity_map import DEFAULT_ALLOWLIST_PATH, IdentityAllowlist
    from ap_chat.manager_client import ManagerBotClient
    from ap_chat.runner import BotRunner
    from ap_chat.telegram.adapter import TelegramPlatform
    from ap_chat.telegram.client import TelegramBotClient
    from ap_chat.telegram.offset_store import OffsetStore

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set - see docs/telegram-bot-setup.md")

    fathm_home = Path.home() / ".fathm"
    allowlist_path = Path(os.environ.get("AP_CHAT_ALLOWLIST_PATH", str(DEFAULT_ALLOWLIST_PATH)))
    offset_path = Path(os.environ.get("AP_CHAT_OFFSET_PATH", str(fathm_home / "chat_telegram_offset.json")))
    manager_base_url = os.environ.get("AP_CHAT_MANAGER_BASE_URL", "http://127.0.0.1:8000")
    console_base_url = os.environ.get("AP_CHAT_CONSOLE_BASE_URL", f"{manager_base_url.rstrip('/')}/console")
    poll_timeout = int(os.environ.get("AP_CHAT_POLL_TIMEOUT", "30"))
    reply_when_unauthorized = os.environ.get("AP_CHAT_UNAUTHORIZED_REPLY", "true").strip().lower() != "false"

    telegram_client = TelegramBotClient(token=token, timeout=poll_timeout + _POLL_HTTP_TIMEOUT_MARGIN_SECONDS)
    platform = TelegramPlatform(telegram_client, offset_store=OffsetStore(offset_path), poll_timeout=poll_timeout)
    identity_map = IdentityAllowlist(allowlist_path)
    manager_client = ManagerBotClient(base_url=manager_base_url)

    runner = BotRunner(
        platform=platform,
        identity_map=identity_map,
        manager_client=manager_client,
        console_base_url=console_base_url,
        reply_when_unauthorized=reply_when_unauthorized,
    )
    logging.getLogger(__name__).info("fathm planner chat (Telegram) starting, polling as @%s", platform.bot_username)
    runner.run_forever()


if __name__ == "__main__":
    main()
