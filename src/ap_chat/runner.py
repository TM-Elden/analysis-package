"""Platform-neutral polling loop: pulls batches from a `ChatPlatform`, resolves each sender
through the identity allowlist, calls the C4 backend, and posts the reply back in-thread.

Reconnect/backoff (task requirement 5, readiness-report risk #4: "the planner surface silently
dies" if a transport hiccup isn't handled) lives entirely here, not in any platform adapter -
`ChatPlatform.poll()` is allowed to just raise on failure; this is the one place that decides what
"recover without manual intervention" means (exponential backoff, capped, reset on the next
success).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ap_chat.core import ChatPlatform, IncomingMessage, OutgoingReply
from ap_chat.formatting import build_reply_body
from ap_chat.identity_map import IdentityAllowlist
from ap_chat.manager_client import ManagerBotClient, ManagerClientError

logger = logging.getLogger(__name__)

DEFAULT_MIN_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_BACKOFF_SECONDS = 60.0

UNAUTHORIZED_REPLY_TEXT = (
    "You're not registered for the fathm planner bot yet. Ask a fathm admin to provision you a "
    "service account and add you to the bot's allowlist."
)
BACKEND_ERROR_REPLY_TEXT = "Sorry, I couldn't reach the fathm backend just now - please try again shortly."


@dataclass
class RunnerStats:
    """Test/observability seam: counts, not behavior - lets tests assert "it recovered" without
    scraping log output."""

    poll_failures: int = 0
    messages_handled: int = 0
    unauthorized_replies: int = 0
    backend_errors: int = 0


class BotRunner:
    def __init__(
        self,
        *,
        platform: ChatPlatform,
        identity_map: IdentityAllowlist,
        manager_client: ManagerBotClient,
        console_base_url: str | None = None,
        reply_when_unauthorized: bool = True,
        sleep=time.sleep,
        min_backoff_seconds: float = DEFAULT_MIN_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    ):
        self.platform = platform
        self.identity_map = identity_map
        self.manager_client = manager_client
        self.console_base_url = console_base_url
        self.reply_when_unauthorized = reply_when_unauthorized
        self._sleep = sleep
        self._min_backoff = min_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self.stats = RunnerStats()

    def run_forever(self, *, max_poll_cycles: int | None = None) -> None:
        """Runs until `max_poll_cycles` successful poll cycles have completed (`None` = forever -
        the production entrypoint's call). Tests pass a small `max_poll_cycles` to make the loop
        finite and deterministic instead of mocking `while True`."""
        backoff = self._min_backoff
        cycles = 0
        while max_poll_cycles is None or cycles < max_poll_cycles:
            try:
                for batch in self.platform.poll():
                    backoff = self._min_backoff  # any successful cycle resets backoff
                    for message in batch:
                        self._handle_message(message)
                    cycles += 1
                    if max_poll_cycles is not None and cycles >= max_poll_cycles:
                        return
            except Exception:
                self.stats.poll_failures += 1
                logger.warning("getUpdates failed, backing off %.1fs before retry", backoff, exc_info=True)
                self._sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                # Loop back to `while` and call platform.poll() again - a prior generator that
                # raised mid-iteration is not resumed, a fresh poll cycle is started instead.

    def _send_reply(self, reply: OutgoingReply) -> None:
        """Delivery is best-effort from the loop's point of view: `ChatPlatform.send_reply` raises
        on failure (rate limit, oversized message, transient network error), and this is the one
        place that catches it - a lost reply is logged and the loop moves on to the next message
        rather than aborting the rest of the batch or being mistaken for a `getUpdates` poll
        failure by `run_forever`'s backoff handling."""
        try:
            self.platform.send_reply(reply)
        except Exception:
            logger.exception("send_reply failed for conversation %r, message dropped", reply.conversation_id)

    def _handle_message(self, message: IncomingMessage) -> None:
        identity = self.identity_map.resolve(message.platform_user_id)
        if identity is None:
            # P5.4 reload-on-miss: a just-provisioned planner's id won't be in the snapshot the
            # process loaded at startup - reload once and retry before refusing, so provisioning
            # via the console admin flow works without bouncing the systemd unit. Not a file
            # watcher and not per-message: this only fires on an actual resolve-miss, and only
            # once per miss (a genuinely-unmapped id still costs exactly one extra reload, not a
            # retry loop).
            try:
                self.identity_map.load()
            except Exception:
                logger.warning("allowlist reload-on-miss failed, continuing with stale map", exc_info=True)
            else:
                identity = self.identity_map.resolve(message.platform_user_id)
        if identity is None:
            logger.info("refusing message from unmapped platform user %r", message.platform_user_id)
            if self.reply_when_unauthorized:
                self.stats.unauthorized_replies += 1
                self._send_reply(
                    OutgoingReply(
                        conversation_id=message.conversation_id,
                        reply_to_id=message.reply_to_id,
                        body=UNAUTHORIZED_REPLY_TEXT,
                    )
                )
            return

        try:
            answer = self.manager_client.ask(message.text, token=identity.token)
        except ManagerClientError:
            logger.exception("POST /chat/manager failed for fathm user %r", identity.fathm_user_id)
            self.stats.backend_errors += 1
            self._send_reply(
                OutgoingReply(
                    conversation_id=message.conversation_id,
                    reply_to_id=message.reply_to_id,
                    body=BACKEND_ERROR_REPLY_TEXT,
                )
            )
            return

        body, citation_links = build_reply_body(answer, console_base_url=self.console_base_url)
        self.stats.messages_handled += 1
        self._send_reply(
            OutgoingReply(
                conversation_id=message.conversation_id,
                reply_to_id=message.reply_to_id,
                body=body,
                citation_links=citation_links,
            )
        )
