"""End-to-end: a simulated Telegram message triggers a real call shape to the bot backend and a
real reply shape back to Telegram - both HTTP boundaries mocked via `httpx.MockTransport` (task
acceptance criterion: "otherwise mock the Telegram Bot API boundary explicitly and say so in the
report" - no real Telegram bot/chat credentials are available in this environment, so this is the
documented mock path, exercising the exact same `TelegramBotClient` / `ManagerBotClient` code that
talks to the real APIs in production - only the transport is swapped).
"""

from __future__ import annotations

import json

import httpx

from ap_chat.identity_map import IdentityAllowlist
from ap_chat.manager_client import ManagerBotClient
from ap_chat.runner import BotRunner
from ap_chat.telegram.adapter import TelegramPlatform
from ap_chat.telegram.client import TelegramBotClient
from ap_chat.telegram.offset_store import OffsetStore


def test_a_telegram_dm_produces_a_real_backend_call_and_a_real_reply(tmp_path):
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(json.dumps({"42": {"fathm_user_id": "planner.alice", "token": "tok-1"}}))

    telegram_calls = []

    def telegram_handler(request: httpx.Request) -> httpx.Response:
        telegram_calls.append(request)
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "fathm_bot"}})
        if request.url.path.endswith("/getUpdates"):
            offset = request.url.params.get("offset")
            if offset:  # second poll cycle: nothing new, ends the test via max_poll_cycles
                return httpx.Response(200, json={"ok": True, "result": []})
            update = {
                "update_id": 1001,
                "message": {
                    "message_id": 7,
                    "text": "what's the copper forecast?",
                    "from": {"id": 42},
                    "chat": {"id": 555, "type": "private"},
                },
            }
            return httpx.Response(200, json={"ok": True, "result": [update]})
        if request.url.path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 8}})
        raise AssertionError(f"unexpected Telegram call: {request.url}")

    manager_calls = []

    def manager_handler(request: httpx.Request) -> httpx.Response:
        manager_calls.append(request)
        assert request.headers["authorization"] == "Bearer tok-1"
        assert json.loads(request.content) == {"question": "what's the copper forecast?"}
        return httpx.Response(
            200,
            json={
                "answer": "Copper spot moved 4% this week.",
                "refused": False,
                "citations": [{"package_id": "pkg-a", "package_version": "1.0.0", "field_path": "x", "chunk_type": "override"}],
            },
        )

    telegram_client = TelegramBotClient(token="123:test", transport=httpx.MockTransport(telegram_handler))
    platform = TelegramPlatform(telegram_client, offset_store=OffsetStore(tmp_path / "offset.json"), poll_timeout=1)
    identity_map = IdentityAllowlist(allowlist_path)
    manager_client = ManagerBotClient(base_url="http://manager.internal", transport=httpx.MockTransport(manager_handler))

    runner = BotRunner(
        platform=platform, identity_map=identity_map, manager_client=manager_client,
        console_base_url="http://manager.internal/console", sleep=lambda s: None,
    )
    runner.run_forever(max_poll_cycles=1)

    # The backend saw the real question, authenticated as the mapped fathm identity's token.
    assert len(manager_calls) == 1

    # A real reply was posted back to Telegram, in-thread, with the full answer and a citation link.
    send_calls = [r for r in telegram_calls if r.url.path.endswith("/sendMessage")]
    assert len(send_calls) == 1
    sent_params = dict(send_calls[0].url.params)
    assert sent_params["chat_id"] == "555"
    assert sent_params["reply_to_message_id"] == "7"
    assert "Copper spot moved 4% this week." in sent_params["text"]
    assert "http://manager.internal/console/packages/pkg-a" in sent_params["text"]
