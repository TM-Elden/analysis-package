"""TelegramPlatform: DM vs. mention filtering, mention-text stripping, offset persistence, and
reply rendering (HTML escaping + citation links) - against a fake TelegramBotClient stand-in so
these tests focus purely on adapter logic, not HTTP shaping (that's test_chat_telegram_client.py).
"""

from __future__ import annotations

from ap_chat.core import OutgoingReply
from ap_chat.telegram.adapter import TelegramPlatform
from ap_chat.telegram.offset_store import OffsetStore


class FakeTelegramClient:
    def __init__(self, updates_batches):
        self._updates_batches = list(updates_batches)
        self.sent = []

    def get_me(self):
        return {"id": 1, "username": "fathm_bot"}

    def get_updates(self, *, offset, timeout):
        self.last_offset_requested = offset
        return self._updates_batches.pop(0) if self._updates_batches else []

    def send_message(self, *, chat_id, text, reply_to_message_id=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_to_message_id": reply_to_message_id})


def _message(update_id, *, chat_type, text, message_id=1, chat_id=555, user_id=42):
    return {
        "update_id": update_id,
        "message": {"message_id": message_id, "text": text, "from": {"id": user_id}, "chat": {"id": chat_id, "type": chat_type}},
    }


def test_direct_message_is_always_yielded(tmp_path):
    client = FakeTelegramClient([[_message(1, chat_type="private", text="what's the copper forecast?")]])
    platform = TelegramPlatform(client, offset_store=OffsetStore(tmp_path / "offset.json"))
    batch = next(platform.poll())
    assert len(batch) == 1
    assert batch[0].text == "what's the copper forecast?"
    assert batch[0].is_direct is True
    assert batch[0].platform_user_id == "42"


def test_group_message_without_mention_is_dropped(tmp_path):
    client = FakeTelegramClient([[_message(1, chat_type="group", text="just chatting, no mention here")]])
    platform = TelegramPlatform(client, offset_store=OffsetStore(tmp_path / "offset.json"))
    assert next(platform.poll()) == []


def test_group_message_with_mention_is_yielded_with_mention_stripped(tmp_path):
    client = FakeTelegramClient([[_message(1, chat_type="group", text="@fathm_bot what's the copper forecast?")]])
    platform = TelegramPlatform(client, offset_store=OffsetStore(tmp_path / "offset.json"))
    batch = next(platform.poll())
    assert len(batch) == 1
    assert batch[0].text == "what's the copper forecast?"
    assert batch[0].is_direct is False


def test_offset_is_persisted_and_reused_across_poll_cycles(tmp_path):
    offset_path = tmp_path / "offset.json"
    client = FakeTelegramClient([[_message(10, chat_type="private", text="hi")], []])
    platform = TelegramPlatform(client, offset_store=OffsetStore(offset_path))
    gen = platform.poll()
    next(gen)
    assert client.last_offset_requested is None  # first call: no prior offset
    next(gen)
    assert client.last_offset_requested == 11  # update_id 10 acked -> next offset is 11
    assert OffsetStore(offset_path).load() == 11


def test_send_reply_escapes_html_and_renders_citation_links(tmp_path):
    client = FakeTelegramClient([])
    platform = TelegramPlatform(client, offset_store=OffsetStore(tmp_path / "offset.json"))
    reply = OutgoingReply(
        conversation_id="555",
        reply_to_id="1",
        body="Copper <spot> price & terms",
        citation_links=(("pkg-a v1.0.0 (override)", "http://host/console/packages/pkg-a"),),
    )
    platform.send_reply(reply)
    sent = client.sent[0]
    assert sent["chat_id"] == 555
    assert sent["reply_to_message_id"] == 1
    assert "Copper &lt;spot&gt; price &amp; terms" in sent["text"]
    assert '<a href="http://host/console/packages/pkg-a">pkg-a v1.0.0 (override)</a>' in sent["text"]
