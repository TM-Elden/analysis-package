"""`ChatPlatform` implementation over `TelegramBotClient` (task requirement 2: DM or @mention).

A DM (`chat.type == "private"`) is always answered. A group/supergroup message is answered only
when it @mentions the bot's own username (fetched once via `getMe` at startup) - the mention text
is stripped before the question reaches `ap_chat.runner`/the C4 backend, so `"@fathm_bot what's
the copper forecast?"` and a DM'd `"what's the copper forecast?"` produce the same question text.
"""

from __future__ import annotations

from typing import Any, Iterator

from ap_chat.core import IncomingMessage, OutgoingReply
from ap_chat.telegram.client import TelegramBotClient
from ap_chat.telegram.offset_store import OffsetStore

_HTML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def _escape_html(text: str) -> str:
    for char, escaped in _HTML_ESCAPES:
        text = text.replace(char, escaped)
    return text


def _escape_attr(url: str) -> str:
    return _escape_html(url).replace('"', "&quot;")


class TelegramPlatform:
    def __init__(self, client: TelegramBotClient, *, offset_store: OffsetStore, poll_timeout: int = 30):
        self._client = client
        self._offset_store = offset_store
        self._poll_timeout = poll_timeout
        self._bot_username = client.get_me()["username"]

    @property
    def bot_username(self) -> str:
        """The bot's own username, fetched once via `getMe` at construction - exposed so callers
        (e.g. the `__main__` entrypoint's startup log line) don't need a second `getMe` round-trip
        just to display it."""
        return self._bot_username

    def poll(self) -> Iterator[list[IncomingMessage]]:
        while True:
            updates = self._client.get_updates(offset=self._offset_store.load(), timeout=self._poll_timeout)
            batch: list[IncomingMessage] = []
            max_update_id: int | None = None
            for update in updates:
                max_update_id = update["update_id"] if max_update_id is None else max(max_update_id, update["update_id"])
                message = self._to_incoming(update.get("message"))
                if message is not None:
                    batch.append(message)
            if max_update_id is not None:
                # Ack everything up to and including the highest update_id seen, even the ones we
                # decided not to answer (e.g. an unmentioned group message) - those are still
                # "handled" as far as Telegram redelivery is concerned.
                self._offset_store.save(max_update_id + 1)
            yield batch

    def _to_incoming(self, message: dict[str, Any] | None) -> IncomingMessage | None:
        if not message or "text" not in message or "from" not in message:
            return None
        chat = message["chat"]
        text = message["text"]
        is_direct = chat.get("type") == "private"
        if not is_direct:
            mention = f"@{self._bot_username}"
            lowered = text.lower()
            idx = lowered.find(mention.lower())
            if idx == -1:
                return None
            text = (text[:idx] + text[idx + len(mention):]).strip()
        if not text:
            return None
        return IncomingMessage(
            platform_user_id=str(message["from"]["id"]),
            conversation_id=str(chat["id"]),
            reply_to_id=str(message["message_id"]),
            text=text,
            is_direct=is_direct,
        )

    def send_reply(self, reply: OutgoingReply) -> None:
        body = _escape_html(reply.body)
        if reply.citation_links:
            lines = "\n".join(
                f'• <a href="{_escape_attr(url)}">{_escape_html(label)}</a>' if url else f"• {_escape_html(label)}"
                for label, url in reply.citation_links
            )
            body = f"{body}\n\nCitations:\n{lines}"
        self._client.send_message(
            chat_id=int(reply.conversation_id),
            text=body,
            reply_to_message_id=int(reply.reply_to_id),
        )
