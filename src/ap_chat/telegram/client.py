"""Raw Telegram Bot API client - plain `httpx`, no SDK dependency (task requirement 1), same
`transport=` test seam pattern as `ap_manager_bot.llm_client.AnthropicHTTPClient` and
`ap_chat.manager_client.ManagerBotClient`.

Long-polling only: `get_updates` calls `getUpdates` with a `timeout` param (the Bot API's own
server-side long-poll wait), never a webhook - no public HTTPS endpoint needed on a host with no
ingress, the same property Socket Mode would have given on Slack (readiness report section 5.5).
"""

from __future__ import annotations

from typing import Any

import httpx

_API_BASE = "https://api.telegram.org"


class TelegramClientError(Exception):
    """Raised on a transport-level failure, a non-2xx HTTP response, or `{"ok": false, ...}` in an
    otherwise-200 body (the Bot API's own error convention)."""


class TelegramBotClient:
    def __init__(self, *, token: str, timeout: float = 40.0, transport: httpx.BaseTransport | None = None):
        if not token:
            raise TelegramClientError("a bot token is required (see docs/telegram-bot-setup.md for BotFather registration)")
        self._base = f"{_API_BASE}/bot{token}"
        # `transport` is a test seam (httpx.MockTransport); production leaves it unset and gets a
        # real HTTPS connection pool. Timeout must exceed the longest `getUpdates` long-poll wait
        # we ever pass, or every poll would look like a transport failure.
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelegramBotClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        response = self._client.get(f"{self._base}/{method}", params=params)
        if response.status_code >= 400:
            raise TelegramClientError(f"{method} returned HTTP {response.status_code}: {response.text}")
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramClientError(f"{method} returned a non-JSON body: {response.text!r}") from exc
        if not body.get("ok"):
            raise TelegramClientError(f"{method} returned ok=false: {body}")
        return body["result"]

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe", {})

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", params)

    def send_message(self, *, chat_id: int, text: str, reply_to_message_id: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            params["reply_to_message_id"] = reply_to_message_id
        return self._call("sendMessage", params)
