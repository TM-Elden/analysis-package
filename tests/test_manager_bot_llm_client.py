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
    return AnthropicHTTPClient(api_key="test-key", model="claude-sonnet-5", transport=httpx.MockTransport(handler))


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


def test_missing_api_key_construction_does_not_raise_but_first_call_does(monkeypatch):
    """D5 (`data/fathm-mvp-review/report.md` section 5 item 5): construction must never raise -
    it happens inside FastAPI dependency resolution, before a route body (and that route's own
    clean-error handling) ever runs. The failure is deferred to `complete()`, the first point that
    actually needs the key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = AnthropicHTTPClient(api_key=None, model="claude-sonnet-5")
    with pytest.raises(LLMClientError, match="ANTHROPIC_API_KEY"):
        client.complete(system="s", messages=[], tools=[])
    client.close()


def test_missing_model_construction_does_not_raise_but_first_call_does(monkeypatch):
    """D6 companion to the above: AP_MANAGER_BOT_MODEL has no silent default (see llm_client.py's
    module-level comment) and is checked the same lazily-deferred way."""
    monkeypatch.delenv("AP_MANAGER_BOT_MODEL", raising=False)
    client = AnthropicHTTPClient(api_key="test-key", model=None)
    with pytest.raises(LLMClientError, match="AP_MANAGER_BOT_MODEL"):
        client.complete(system="s", messages=[], tools=[])
    client.close()


def test_env_vars_resolved_at_construction_time_not_import_time(monkeypatch):
    """D6: the old `DEFAULT_MODEL = os.environ.get(...)` module-level assignment froze the value at
    import time, so setting the env var afterwards had no effect. Construction-time resolution
    fixes that - this exercises it directly rather than relying on process import order."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AP_MANAGER_BOT_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "late-key")
    monkeypatch.setenv("AP_MANAGER_BOT_MODEL", "claude-sonnet-5")
    client = AnthropicHTTPClient()
    assert client.api_key == "late-key"
    assert client.model == "claude-sonnet-5"
    client.close()
