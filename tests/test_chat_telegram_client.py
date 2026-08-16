"""TelegramBotClient request/response shaping against an httpx.MockTransport - no real network
call, no bot token needed (mirrors tests/test_manager_bot_llm_client.py's approach for the
Anthropic client)."""

from __future__ import annotations

import httpx
import pytest

from ap_chat.telegram.client import TelegramBotClient, TelegramClientError


def _client(handler) -> TelegramBotClient:
    return TelegramBotClient(token="123:test-token", transport=httpx.MockTransport(handler))


def test_get_me_hits_the_right_endpoint_and_returns_the_result_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "fathm_bot"}})

    client = _client(handler)
    result = client.get_me()
    assert captured["url"] == "https://api.telegram.org/bot123:test-token/getMe"
    assert result["username"] == "fathm_bot"
    client.close()


def test_get_updates_passes_offset_and_timeout():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = _client(handler)
    client.get_updates(offset=42, timeout=30)
    assert captured["params"]["offset"] == "42"
    assert captured["params"]["timeout"] == "30"
    client.close()


def test_get_updates_omits_offset_when_none():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = _client(handler)
    client.get_updates(offset=None, timeout=30)
    assert "offset" not in captured["params"]
    client.close()


def test_send_message_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    client = _client(handler)
    client.send_message(chat_id=99, text="hi", reply_to_message_id=5)
    assert captured["params"]["chat_id"] == "99"
    assert captured["params"]["text"] == "hi"
    assert captured["params"]["reply_to_message_id"] == "5"
    assert captured["params"]["parse_mode"] == "HTML"
    client.close()


def test_non_2xx_raises_telegram_client_error():
    client = _client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(TelegramClientError, match="500"):
        client.get_me()
    client.close()


def test_ok_false_body_raises_telegram_client_error():
    client = _client(lambda request: httpx.Response(200, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(TelegramClientError, match="ok=false"):
        client.get_me()
    client.close()


def test_missing_token_raises_before_any_call():
    with pytest.raises(TelegramClientError, match="bot token"):
        TelegramBotClient(token="")
