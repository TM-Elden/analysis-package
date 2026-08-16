"""C4 acceptance eval set (design doc section 8: "Eval set: N questions with expected package
citations"; report section 5.3/P3.3: "propose N=15 questions against a seeded synthetic corpus of
~8 packages"). Each question's answer is checked for citation correctness against a known-correct
package, not just "did it respond" - see `_EVAL_QUESTIONS`.

Uses `ScriptedLLMClient` (tests/_manager_bot_fake_llm.py) in place of a live model call - see that
module's docstring for why that's the right substitution for this suite.
"""

from __future__ import annotations

import pytest

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_manager_bot.service import NO_EVIDENCE_ANSWER, ManagerBot

from _manager_bot_corpus import build_corpus
from _manager_bot_fake_llm import ScriptedLLMClient

TEAM_READER = Identity(id="planner.eval", roles=frozenset({Role.TEAM_READER}))
ANALYST = Identity(id="lead.eval", roles=frozenset({Role.ANALYST}))

# (question, expected scenario label, caller identity). All but the last two questions are answered
# by TEAM_READER, the base tier every corpus package (except vaulttec_relay) is visible to.
_EVAL_QUESTIONS: tuple[tuple[str, str, Identity], ...] = (
    ("Why did we hold quantity for ACME BBU-100?", "acme_bbu", TEAM_READER),
    ("What override applies to GLOBEX PSU-75 and why?", "globex_psu", TEAM_READER),
    ("What's the exception for INITECH CAP-20?", "initech_cap", TEAM_READER),
    ("Summarize the data snapshot correction for UMBRELLA RELAY-40.", "umbrella_relay", TEAM_READER),
    ("What NPI bridge manual override applies to WAYNE BBU-200?", "wayne_bbu", TEAM_READER),
    ("What's the reason for the STARK PSU-90 override?", "stark_psu", TEAM_READER),
    ("Why was WONKA CAP-55 quantity held?", "wonka_cap", TEAM_READER),
    ("What judgment did we log about GLOBEX PSU-75 risk?", "globex_psu", TEAM_READER),
    ("What planning truth applies to ACME BBU-100 sourcing?", "acme_bbu", TEAM_READER),
    ("Summarize the run for the INITECH CAP-20 pack.", "initech_cap", TEAM_READER),
    ("List exceptions for WAYNE BBU-200.", "wayne_bbu", TEAM_READER),
    ("Why was the STARK PSU-90 change flagged OTHER?", "stark_psu", TEAM_READER),
    ("What's driving the WONKA CAP-55 volume cut this cycle?", "wonka_cap", TEAM_READER),
    ("What override applies to UMBRELLA RELAY-40 and why?", "umbrella_relay", TEAM_READER),
    # Elevated-role caller, restricted-tier package - citation-correctness case, not a refusal case.
    ("What supplier risk split change applies to VAULT-TEC RELAY-99?", "vaulttec_relay", ANALYST),
)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("manager-bot-eval-corpus")
    c = build_corpus(tmp_path)
    yield c
    c.store.close()
    c.index.close()


@pytest.mark.parametrize("question,expected_label,identity", _EVAL_QUESTIONS)
def test_eval_question_cites_the_known_correct_package(corpus, question, expected_label, identity):
    bot = ManagerBot(index=corpus.index, store=corpus.store, llm_client=ScriptedLLMClient())
    answer = bot.answer(question, identity=identity)

    assert not answer.refused, f"expected a grounded answer, got a refusal: {answer.answer!r}"
    assert answer.citations, "an accepted answer must carry at least one citation"
    expected_package_id = corpus.package_ids[expected_label]
    assert any(c.package_id == expected_package_id for c in answer.citations), (
        f"expected a citation to {expected_label} ({expected_package_id}), got "
        f"{[(c.package_id, c.field_path) for c in answer.citations]}"
    )


def test_question_with_no_matching_package_is_refused_not_hallucinated(corpus):
    bot = ManagerBot(index=corpus.index, store=corpus.store, llm_client=ScriptedLLMClient())
    answer = bot.answer("What override applies to SPACELY SPROCKETS part COG-9000?", identity=TEAM_READER)

    assert answer.refused is True
    assert answer.citations == ()
    assert answer.answer == NO_EVIDENCE_ANSWER
