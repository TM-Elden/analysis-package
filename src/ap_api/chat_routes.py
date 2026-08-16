"""POST /chat/manager - the C4 manager bot endpoint (design doc section 8; report section 5.3).

Any authenticated identity may call this route (no `require_any_role` gate) - scoping is not a
route-level role check the way `POST /packages` is, it's per-chunk filtering inside the tool loop
(`ap_manager_bot.scoping`) so a `team_reader` and an `admin` hitting this same route legitimately see
different evidence, not different HTTP status codes. See CLAUDE.md's C4 section for the full
architecture.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ap_api.deps import get_index, get_llm_client, get_store, identity_from_request
from ap_api.schemas import ChatRequest, ChatResponse, chat_answer_to_out
from ap_auth.identity import Identity
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import LLMClient
from ap_manager_bot.service import ManagerBot
from ap_store.store import PackageStore

router = APIRouter()


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
