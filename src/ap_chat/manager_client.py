"""HTTP client for `POST /chat/manager` (`ap_api/chat_routes.py`) - the same C4 backend the console
query panel (P3.7, later) will front. Plain `httpx`, same `transport=` test seam pattern as
`ap_manager_bot.llm_client.AnthropicHTTPClient` (`httpx.MockTransport` in tests, a real connection
pool in production).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class ManagerClientError(Exception):
    """Raised on a non-2xx response or a malformed response body."""


@dataclass(frozen=True)
class ChatCitation:
    package_id: str
    package_version: str
    field_path: str
    chunk_type: str


@dataclass(frozen=True)
class ChatAnswer:
    answer: str
    refused: bool
    citations: tuple[ChatCitation, ...]


class ManagerBotClient:
    """Talks to a running `ap-api` server's `POST /chat/manager`, authenticating as whatever
    identity `token` maps to (a service-account bearer token issued by `ap-auth token`) - the
    caller's role/scoping is entirely the server's `identity_from_request` + `ManagerBot`
    concern, not this client's."""

    def __init__(self, *, base_url: str, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        # `transport` is a test seam; production leaves it unset and gets a real HTTPS/HTTP pool.
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ManagerBotClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ask(self, question: str, *, token: str) -> ChatAnswer:
        response = self._client.post(
            f"{self.base_url}/chat/manager",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": question},
        )
        if response.status_code >= 400:
            raise ManagerClientError(f"/chat/manager returned {response.status_code}: {response.text}")
        try:
            body = response.json()
        except ValueError as exc:
            raise ManagerClientError(f"/chat/manager returned a non-JSON body: {response.text!r}") from exc

        try:
            citations = tuple(
                ChatCitation(
                    package_id=c["package_id"],
                    package_version=c["package_version"],
                    field_path=c["field_path"],
                    chunk_type=c["chunk_type"],
                )
                for c in body["citations"]
            )
            return ChatAnswer(answer=body["answer"], refused=body["refused"], citations=citations)
        except (KeyError, TypeError) as exc:
            raise ManagerClientError(f"/chat/manager returned an unexpected body shape: {body!r}") from exc
