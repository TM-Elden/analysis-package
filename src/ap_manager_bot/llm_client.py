"""LLM client for the C4 tool-using loop.

**Captain-approved egress posture** (resolved decision `fathm-phase3-readiness-decision-llm-egress-posture`,
2026-08-16): the bot may send retrieved, redacted, in-scope package content to a frontier-model API
at query time, under that provider's no-training API terms, as a documented deliberate inference-time
exception to TRUST.md's "no default outbound ship of package bodies to third parties" (see CLAUDE.md's
C4 section). This is an explicit stance, not a silent default - do not swap providers here without a
matching captain decision.

Per the readiness report (section 5.3): "Anthropic API over httpx - plain HTTPS/JSON, no SDK
dependency needed in the apt-only sandbox." `AnthropicHTTPClient` speaks the Messages API's raw JSON
shape directly rather than wrapping it in a typed request/response model - there is exactly one
caller (`service.py`'s tool loop) and no second provider planned, so a typed abstraction here would
cost more than it buys; the seam for a second provider is this whole module (implement `LLMClient`),
not a leaky partial abstraction inside it.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

#: Overridable so a tenant can pin whichever model id the captain's posture approves; no single
#: model id is "the" approved one baked in here - see the module docstring.
DEFAULT_MODEL = os.environ.get("AP_MANAGER_BOT_MODEL", "claude-sonnet-5")
_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024


class LLMClientError(Exception):
    """Raised on a non-2xx response, a missing API key, or a malformed response body."""


class LLMClient(Protocol):
    def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """One Messages-API-shaped turn: returns the raw parsed response body (`{"content": [...],
        "stop_reason": ..., ...}`), not a typed wrapper - see module docstring for why."""
        ...


class AnthropicHTTPClient:
    """Production `LLMClient`: plain HTTPS/JSON against the Anthropic Messages API, no SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMClientError(
                "ANTHROPIC_API_KEY is not set - required to call the captain-approved frontier-model "
                "API (see llm_client.py module docstring for the egress-posture decision this backs)"
            )
        self.model = model
        # `transport` is a test seam (httpx.MockTransport) - production never sets it, so this
        # still opens a real HTTPS connection pool by default.
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AnthropicHTTPClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.post(
            _API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": _API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "system": system,
                "messages": messages,
                "tools": tools,
            },
        )
        if response.status_code >= 400:
            raise LLMClientError(f"Anthropic API returned {response.status_code}: {response.text}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMClientError(f"Anthropic API returned a non-JSON body: {response.text!r}") from exc
