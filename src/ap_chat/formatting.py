"""Builds the platform-neutral reply body + citation links from a `ManagerBotClient` answer
(captain-approved posting policy: full answer text with citations, in-thread -
`fm-decision-hold.sh id fathm-phase3-readiness chat-answer-posting-policy`).

Kept separate from any platform's markup rules on purpose: a Telegram adapter renders
`citation_links` as HTML `<a href>` tags, a future Slack adapter would render the same tuples as
`<url|label>` - this module never emits platform-specific syntax.
"""

from __future__ import annotations

from ap_chat.manager_client import ChatAnswer


def package_console_url(console_base_url: str, package_id: str) -> str:
    """Link into the P3.4 console's package detail page (`ap_console/routes.py`'s
    `GET /console/packages/{package_id}`) - `console_base_url` is expected to already include the
    `/console` prefix (e.g. `http://host:8000/console`) so this module doesn't need to know it."""
    return f"{console_base_url.rstrip('/')}/packages/{package_id}"


def citation_label(citation) -> str:
    return f"{citation.package_id} v{citation.package_version} ({citation.chunk_type})"


def build_reply_body(
    answer: ChatAnswer, *, console_base_url: str | None
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    """Returns `(body_text, citation_links)`. Each entry is `(label, url)`; `url` is `None` when
    `console_base_url` is not configured (only the hyperlink degrades gracefully, never the
    citation itself - required posting policy is "citations rendered as links ... where possible",
    which qualifies the link rendering, not whether a citation appears) or when the answer carries
    no citations at all (a refusal, or - structurally impossible today per
    `ManagerBot._final_answer`'s citation-enforcement, but harmless either way - a bare answer)."""
    if not console_base_url:
        return answer.answer, tuple((citation_label(c), None) for c in answer.citations)
    links = tuple((citation_label(c), package_console_url(console_base_url, c.package_id)) for c in answer.citations)
    return answer.answer, links
