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

#: Required, not defaulted (D6, `data/fathm-mvp-review/report.md` section 5 item 5): a tenant must
#: pin whichever model id the captain's posture approves via AP_MANAGER_BOT_MODEL - there is no
#: silent fallback baked in here, see the module docstring. Resolved at AnthropicHTTPClient
#: construction time (not import time), so setting the env var after import still takes effect -
#: see `__init__` below.
_MODEL_ENV_VAR = "AP_MANAGER_BOT_MODEL"
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
        model: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        # Deliberately does NOT raise here (D5, `data/fathm-mvp-review/report.md` section 5 item 5):
        # this constructor runs inside FastAPI dependency resolution (`ap_api/deps.py::get_llm_client`),
        # *before* a route body executes - raising here would produce a raw 500 that never reaches
        # any of the three call sites' own clean-error handling (the SSE route's error event, the
        # JSON route's HTTPException mapping, the console sweep button's inline flash). Missing
        # config is instead surfaced from `complete()`, the first point that actually needs it - see
        # that method below. Also resolved here (construction time), not at import time (the old
        # module-level `DEFAULT_MODEL = os.environ.get(...)` bug this replaces) - setting either env
        # var after import now takes effect on the next `get_llm_client()` call.
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get(_MODEL_ENV_VAR)
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
        if not self.api_key:
            raise LLMClientError(
                "ANTHROPIC_API_KEY is not set - required to call the captain-approved frontier-model "
                "API (see llm_client.py module docstring for the egress-posture decision this backs)"
            )
        if not self.model:
            raise LLMClientError(
                f"{_MODEL_ENV_VAR} is not set - required model id, no default is baked in (D6, "
                "see llm_client.py module docstring and CLAUDE.md's C4 section)"
            )
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
