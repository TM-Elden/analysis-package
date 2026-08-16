"""BotRunner: end-to-end message handling (allowlist resolution -> backend call -> reply with
citations) against fake platform/identity-map/manager-client seams, plus the reconnect/backoff
acceptance test (task acceptance criterion: "simulate a failed getUpdates call, confirm the app
recovers without manual intervention") - here generalized to any `ChatPlatform.poll()` failure,
not Telegram-specific, since the runner itself is platform-neutral.
"""

from __future__ import annotations

from ap_chat.core import IncomingMessage, OutgoingReply
from ap_chat.identity_map import IdentityAllowlist, MappedIdentity
from ap_chat.manager_client import ChatAnswer, ChatCitation, ManagerClientError
from ap_chat.runner import BACKEND_ERROR_REPLY_TEXT, UNAUTHORIZED_REPLY_TEXT, BotRunner


class FakePlatform:
    """`_plan` is a list of per-`poll()`-call items: either a list of message batches to yield
    (success) or an `Exception` instance to raise mid-iteration (simulated transport failure)."""

    def __init__(self, plan):
        self._plan = list(plan)
        self.sent: list[OutgoingReply] = []

    def poll(self):
        item = self._plan.pop(0)
        if isinstance(item, Exception):
            raise item
        for batch in item:
            yield batch

    def send_reply(self, reply: OutgoingReply) -> None:
        self.sent.append(reply)


class FakeIdentityMap:
    def __init__(self, mapping: dict[str, MappedIdentity]):
        self._mapping = mapping

    def resolve(self, platform_user_id: str) -> MappedIdentity | None:
        return self._mapping.get(platform_user_id)


class FakeManagerClient:
    def __init__(self, *, answer: ChatAnswer | None = None, error: Exception | None = None):
        self._answer = answer
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def ask(self, question: str, *, token: str) -> ChatAnswer:
        self.calls.append((question, token))
        if self._error is not None:
            raise self._error
        return self._answer


def _msg(text="what's the copper forecast?", user="42"):
    return IncomingMessage(platform_user_id=user, conversation_id="555", reply_to_id="1", text=text, is_direct=True)


def test_recognized_user_gets_a_cited_reply_from_the_backend():
    citation = ChatCitation(package_id="pkg-a", package_version="1.0.0", field_path="x", chunk_type="override")
    answer = ChatAnswer(answer="Copper spot moved 4%.", refused=False, citations=(citation,))
    platform = FakePlatform([[[_msg()]]])
    identity_map = FakeIdentityMap({"42": MappedIdentity(fathm_user_id="planner.alice", token="tok-1")})
    manager_client = FakeManagerClient(answer=answer)

    runner = BotRunner(
        platform=platform, identity_map=identity_map, manager_client=manager_client,
        console_base_url="http://host/console", sleep=lambda s: None,
    )
    runner.run_forever(max_poll_cycles=1)

    assert manager_client.calls == [("what's the copper forecast?", "tok-1")]
    assert len(platform.sent) == 1
    reply = platform.sent[0]
    assert reply.body == "Copper spot moved 4%."
    assert reply.citation_links == (("pkg-a v1.0.0 (override)", "http://host/console/packages/pkg-a"),)
    assert runner.stats.messages_handled == 1


def test_unmapped_user_gets_a_polite_refusal_and_no_backend_call():
    platform = FakePlatform([[[_msg(user="999")]]])
    identity_map = FakeIdentityMap({})
    manager_client = FakeManagerClient(answer=None)

    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert manager_client.calls == []
    assert platform.sent[0].body == UNAUTHORIZED_REPLY_TEXT
    assert runner.stats.unauthorized_replies == 1


def test_unmapped_user_is_silently_dropped_when_unauthorized_reply_disabled():
    platform = FakePlatform([[[_msg(user="999")]]])
    identity_map = FakeIdentityMap({})
    manager_client = FakeManagerClient(answer=None)

    runner = BotRunner(
        platform=platform, identity_map=identity_map, manager_client=manager_client,
        reply_when_unauthorized=False, sleep=lambda s: None,
    )
    runner.run_forever(max_poll_cycles=1)

    assert platform.sent == []


def test_backend_error_gets_a_graceful_reply_not_a_crash():
    platform = FakePlatform([[[_msg()]]])
    identity_map = FakeIdentityMap({"42": MappedIdentity(fathm_user_id="planner.alice", token="tok-1")})
    manager_client = FakeManagerClient(error=ManagerClientError("boom"))

    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert platform.sent[0].body == BACKEND_ERROR_REPLY_TEXT
    assert runner.stats.backend_errors == 1


def test_a_failed_poll_backs_off_then_recovers_without_manual_intervention():
    """The core reconnect/backoff acceptance test: two consecutive simulated getUpdates failures,
    then a successful cycle that yields a real message - the runner must survive both failures on
    its own and still deliver the reply, with no exception escaping `run_forever`."""
    platform = FakePlatform([RuntimeError("getUpdates: connection reset"), RuntimeError("getUpdates: timeout"), [[_msg()]]])
    identity_map = FakeIdentityMap({"42": MappedIdentity(fathm_user_id="planner.alice", token="tok-1")})
    answer = ChatAnswer(answer="ok", refused=False, citations=())
    manager_client = FakeManagerClient(answer=answer)

    slept: list[float] = []
    runner = BotRunner(
        platform=platform, identity_map=identity_map, manager_client=manager_client,
        sleep=slept.append, min_backoff_seconds=1.0, max_backoff_seconds=60.0,
    )
    runner.run_forever(max_poll_cycles=1)

    assert runner.stats.poll_failures == 2
    assert slept == [1.0, 2.0]  # exponential backoff, doubling each consecutive failure
    assert len(platform.sent) == 1
    assert platform.sent[0].body == "ok"


def test_backoff_resets_after_a_successful_cycle():
    platform = FakePlatform([RuntimeError("boom"), [[]], RuntimeError("boom again"), [[]]])
    identity_map = FakeIdentityMap({})
    manager_client = FakeManagerClient(answer=None)

    slept: list[float] = []
    runner = BotRunner(
        platform=platform, identity_map=identity_map, manager_client=manager_client,
        sleep=slept.append, min_backoff_seconds=1.0, max_backoff_seconds=60.0,
    )
    runner.run_forever(max_poll_cycles=2)

    # Both failures back off from the same base (1.0), because the intervening success reset it -
    # if backoff didn't reset, the second sleep would be 2.0.
    assert slept == [1.0, 1.0]
