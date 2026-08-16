"""ManagerBotClient: POST /chat/manager request shaping against an httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from ap_chat.manager_client import ManagerBotClient, ManagerClientError


def _client(handler) -> ManagerBotClient:
    return ManagerBotClient(base_url="http://testserver", transport=httpx.MockTransport(handler))


def test_ask_sends_bearer_token_and_question_and_parses_citations():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answer": "Copper spot moved 4%.",
                "refused": False,
                "citations": [{"package_id": "pkg-a", "package_version": "1.0.0", "field_path": "labels.overrides[0]", "chunk_type": "override"}],
            },
        )

    client = _client(handler)
    answer = client.ask("what's the copper forecast?", token="tok-1")

    assert captured["url"] == "http://testserver/chat/manager"
    assert captured["headers"]["authorization"] == "Bearer tok-1"
    assert captured["body"] == {"question": "what's the copper forecast?"}
    assert answer.answer == "Copper spot moved 4%."
    assert answer.refused is False
    assert answer.citations[0].package_id == "pkg-a"
    client.close()


def test_non_2xx_raises_manager_client_error():
    client = _client(lambda request: httpx.Response(401, text="unauthorized"))
    with pytest.raises(ManagerClientError, match="401"):
        client.ask("q", token="bad-token")
    client.close()


def test_unexpected_body_shape_raises_manager_client_error():
    client = _client(lambda request: httpx.Response(200, json={"unexpected": "shape"}))
    with pytest.raises(ManagerClientError, match="unexpected"):
        client.ask("q", token="tok-1")
    client.close()
