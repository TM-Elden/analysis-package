"""Platform-neutral shapes and the `ChatPlatform` boundary every adapter implements.

Nothing here mentions Telegram, Slack, or any other platform by name - that's the point (see the
package docstring). A platform adapter's job is to turn its own wire format into `IncomingMessage`
and turn an `OutgoingReply` into whatever its own send call needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol


@dataclass(frozen=True)
class IncomingMessage:
    """One inbound chat message the bot should consider answering.

    `platform_user_id` is the platform's own sender identifier (a Telegram user id today, a Slack
    user id later) - the raw key `identity_map` looks up, never a fathm identity itself.
    `is_direct` distinguishes a DM from a group/channel mention so `runner.py` can apply "answer
    every DM, but only an explicit @mention in a group" without knowing which platform it's on.
    `conversation_id` + `reply_to_id` are whatever the platform needs to address a reply back to
    the same thread/chat - opaque strings from `core`'s point of view.
    """

    platform_user_id: str
    conversation_id: str
    reply_to_id: str
    text: str
    is_direct: bool


@dataclass(frozen=True)
class OutgoingReply:
    """A reply the runner asks the platform adapter to deliver. `citation_links` is a
    platform-neutral `(label, url)` list - `formatting.py` builds these, each adapter renders them
    in its own markup (Telegram HTML `<a href>`, a future Slack `<url|label>`, etc.)."""

    conversation_id: str
    reply_to_id: str
    body: str
    citation_links: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class ChatPlatform(Protocol):
    """The seam a platform adapter implements. `poll()` is a blocking generator so `runner.py` can
    wrap each `next()` in its own reconnect/backoff policy without the platform adapter needing to
    know anything about retries - a failed poll just raises, the runner decides what to do next."""

    def poll(self) -> Iterator[list[IncomingMessage]]:
        """Yield batches of new messages, one batch per successful poll cycle. Raises on a
        transport failure (network error, non-2xx) rather than swallowing it - `runner.py` is the
        layer responsible for catching, backing off, and resuming."""
        ...

    def send_reply(self, reply: OutgoingReply) -> None:
        """Deliver one reply. Raises on failure; the runner logs and moves on rather than
        crashing the whole loop over one undeliverable reply."""
        ...
