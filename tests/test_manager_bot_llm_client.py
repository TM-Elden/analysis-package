"""AnthropicHTTPClient request/response shaping, against an httpx.MockTransport - no real network
call, no ANTHROPIC_API_KEY needed. Confirms the raw-HTTPS integration actually speaks the Messages
API shape (model/system/messages/tools in the request; content/stop_reason parsed from the
response), independent of the harness tests in test_manager_bot*.py that use ScriptedLLMClient."""

from __future__ import annotations

import json

import httpx
import pytest

from ap_manager_bot.llm_client import AnthropicHTTPClient, LLMClientError


def _client(handler) -> AnthropicHTTPClient:
    return AnthropicHTTPClient(api_key="test-key", transport=httpx.MockTransport(handler))


def test_complete_sends_the_messages_api_request_shape_and_parses_the_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"})

    client = _client(handler)
    response = client.complete(system="sys", messages=[{"role": "user", "content": "hello"}], tools=[{"name": "t"}])

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"]
    assert captured["body"]["system"] == "sys"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["body"]["tools"] == [{"name": "t"}]
    assert response["stop_reason"] == "end_turn"
    client.close()


def test_non_2xx_response_raises_llm_client_error():
    client = _client(lambda request: httpx.Response(429, text="rate limited"))
    with pytest.raises(LLMClientError, match="429"):
        client.complete(system="s", messages=[], tools=[])
    client.close()


def test_missing_api_key_raises_before_any_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMClientError, match="ANTHROPIC_API_KEY"):
        AnthropicHTTPClient(api_key=None)
