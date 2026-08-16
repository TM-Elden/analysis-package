"""POST /chat/manager - the C4 manager bot endpoint (design doc section 8; report section 5.3).

Any authenticated identity may call this route (no `require_any_role` gate) - scoping is not a
route-level role check the way `POST /packages` is, it's per-chunk filtering inside the tool loop
(`ap_manager_bot.scoping`) so a `team_reader` and an `admin` hitting this same route legitimately see
different evidence, not different HTTP status codes. See CLAUDE.md's C4 section for the full
architecture.

`GET /chat/manager/stream` (report section 6, P3.7) is the same bot behind an SSE response for the
console query panel. It is GET, not POST: the panel's transport is the browser's native
`EventSource`, which cannot attach custom headers or a request body, so the question travels as a
query param and auth travels as the session cookie - and because GET is a safe method,
`identity_from_request` does not demand the `X-Csrf` header the POST route requires (see
`ap_api/deps.py::_UNSAFE_METHODS`). `ManagerBot.answer` is not itself streaming (`llm_client.complete`
is one blocking Messages-API call per turn, and Anthropic streaming was out of scope for this slice -
see CLAUDE.md) - what streams is the *rendering*: the full answer is computed first, then trickled to
the client as a sequence of `message` events so the panel fills in incrementally rather than blocking
on the whole response, exactly like `service.py`'s docstring says the citation contract is enforced
server-side, not just requested - here the *event framing* is the enforced contract, not real
token-level generation streaming. Message text is HTML-escaped before it goes on the wire so the
htmx `sse-swap` default (innerHTML) can render it directly without executing anything a package's
own content might contain; `citations` travels as a JSON payload instead of pre-rendered markup
(building the `/console/packages/...` link shape is presentation logic that belongs to `ap_console`,
not this format-neutral layer - see CLAUDE.md's console module-boundary note) and the console page's
inline script renders it.
"""

from __future__ import annotations

import html
import json
import re
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ap_api.deps import get_index, get_llm_client, get_store, identity_from_request
from ap_api.schemas import ChatRequest, ChatResponse, chat_answer_to_out
from ap_auth.identity import Identity
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import LLMClient
from ap_manager_bot.models import ChatAnswer, Citation
from ap_manager_bot.service import ManagerBot
from ap_store.store import PackageStore

router = APIRouter()

#: Splits on whitespace boundaries, keeping each token's trailing whitespace attached, so joining
#: the yielded chunks back together reproduces the original text exactly (no re-inserted spaces).
_WORD_BOUNDARY = re.compile(r"\S+\s*")


def _sse_event(event: str, data: str) -> str:
    """One SSE frame. `data` is split on literal newlines into multiple `data:` lines per the SSE
    wire format (a bare embedded `\\n` would otherwise terminate the frame early)."""
    body = "".join(f"data: {line}\n" for line in data.splitlines() or [""])
    return f"event: {event}\n{body}\n"


def _citation_payload(citation: Citation) -> dict[str, str]:
    return {
        "package_id": citation.package_id,
        "package_version": citation.package_version,
        "field_path": citation.field_path,
        "chunk_type": citation.chunk_type,
    }


def _stream_answer(bot: ManagerBot, question: str, identity: Identity) -> Iterator[str]:
    try:
        answer: ChatAnswer = bot.answer(question, identity=identity)
    except Exception as exc:  # noqa: BLE001 - any backend failure must reach the panel as a clean
        # error event, never a hung connection or a bare 500 mid-stream (acceptance criterion:
        # "streaming degrades gracefully... if the backend call fails mid-stream").
        yield _sse_event("error", html.escape(str(exc) or exc.__class__.__name__))
        yield _sse_event("done", "")
        return

    for chunk in _WORD_BOUNDARY.findall(answer.answer) or [answer.answer]:
        yield _sse_event("message", html.escape(chunk))

    yield _sse_event("citations", json.dumps([_citation_payload(c) for c in answer.citations]))
    if answer.refused:
        yield _sse_event("refused", "1")
    yield _sse_event("done", "")


@router.post("/chat/manager", response_model=ChatResponse)
def chat_manager(
    body: ChatRequest,
    actor: Annotated[Identity, Depends(identity_from_request)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> ChatResponse:
    bot = ManagerBot(index=index, store=store, llm_client=llm_client)
    answer = bot.answer(body.question, identity=actor)
    return chat_answer_to_out(answer)


@router.get("/chat/manager/stream")
def chat_manager_stream(
    question: str,
    actor: Annotated[Identity, Depends(identity_from_request)],
    store: Annotated[PackageStore, Depends(get_store)],
    index: Annotated[IndexStore, Depends(get_index)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> StreamingResponse:
    bot = ManagerBot(index=index, store=store, llm_client=llm_client)
    return StreamingResponse(
        _stream_answer(bot, question, actor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
