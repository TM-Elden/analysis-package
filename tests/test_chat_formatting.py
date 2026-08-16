"""build_reply_body: citation-link construction, and graceful degradation with no console URL."""

from __future__ import annotations

from ap_chat.formatting import build_reply_body
from ap_chat.manager_client import ChatAnswer, ChatCitation


def _answer(refused=False, citations=()):
    return ChatAnswer(answer="Copper spot moved 4%.", refused=refused, citations=citations)


def test_builds_citation_links_when_console_base_url_configured():
    citation = ChatCitation(package_id="pkg-a", package_version="1.0.0", field_path="x", chunk_type="override")
    body, links = build_reply_body(_answer(citations=(citation,)), console_base_url="http://host/console")
    assert body == "Copper spot moved 4%."
    assert links == (("pkg-a v1.0.0 (override)", "http://host/console/packages/pkg-a"),)


def test_citation_labels_without_urls_when_console_base_url_not_configured():
    citation = ChatCitation(package_id="pkg-a", package_version="1.0.0", field_path="x", chunk_type="override")
    body, links = build_reply_body(_answer(citations=(citation,)), console_base_url=None)
    assert body == "Copper spot moved 4%."
    assert links == (("pkg-a v1.0.0 (override)", None),)


def test_no_links_when_answer_has_no_citations():
    body, links = build_reply_body(_answer(), console_base_url="http://host/console")
    assert links == ()
