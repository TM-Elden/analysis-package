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
        self.load_calls = 0

    def resolve(self, platform_user_id: str) -> MappedIdentity | None:
        return self._mapping.get(platform_user_id)

    def load(self) -> None:
        """No-op by default - mirrors `IdentityAllowlist.load()`'s signature so the runner's
        reload-on-miss call succeeds against this fake too. Tests that actually want a reload to
        surface a new mapping mutate `_mapping` directly or use `MutatingIdentityMap` below."""
        self.load_calls += 1


class MutatingIdentityMap(FakeIdentityMap):
    """A `load()` that actually picks up a change - simulates an operator (or the console's
    provisioning flow) writing a new allowlist row between the runner's initial resolve-miss and
    its reload."""

    def __init__(self, mapping: dict[str, MappedIdentity], *, added_on_load: dict[str, MappedIdentity]):
        super().__init__(dict(mapping))
        self._added_on_load = added_on_load

    def load(self) -> None:
        super().load()
        self._mapping.update(self._added_on_load)


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


# -- P5.4 reload-on-miss: a just-provisioned planner's first message must work without a restart --


def test_resolve_miss_reloads_the_allowlist_once_and_retries():
    """A platform user id absent from the loaded snapshot but present after `load()` (simulating a
    just-provisioned row) resolves on the same message, no restart - and a genuinely-unmapped id
    still refuses after exactly one reload attempt, not a retry loop."""
    citation = ChatCitation(package_id="pkg-a", package_version="1.0.0", field_path="x", chunk_type="override")
    answer = ChatAnswer(answer="ok", refused=False, citations=(citation,))
    platform = FakePlatform([[[_msg(user="777")]]])
    identity_map = MutatingIdentityMap({}, added_on_load={"777": MappedIdentity(fathm_user_id="planner.new", token="tok-new")})
    manager_client = FakeManagerClient(answer=answer)

    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert identity_map.load_calls == 1
    assert manager_client.calls == [(_msg(user="777").text, "tok-new")]
    assert runner.stats.messages_handled == 1
    assert runner.stats.unauthorized_replies == 0


def test_resolve_miss_that_stays_a_miss_after_reload_still_refuses_exactly_once():
    platform = FakePlatform([[[_msg(user="999")]]])
    identity_map = FakeIdentityMap({})
    manager_client = FakeManagerClient(answer=None)

    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert identity_map.load_calls == 1
    assert manager_client.calls == []
    assert platform.sent[0].body == UNAUTHORIZED_REPLY_TEXT
    assert runner.stats.unauthorized_replies == 1


def test_a_resolved_hit_never_triggers_a_reload():
    platform = FakePlatform([[[_msg()]]])
    identity_map = FakeIdentityMap({"42": MappedIdentity(fathm_user_id="planner.alice", token="tok-1")})
    manager_client = FakeManagerClient(answer=ChatAnswer(answer="ok", refused=False, citations=()))

    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert identity_map.load_calls == 0


def test_reload_on_miss_against_the_real_allowlist_file(tmp_path):
    """Real end-to-end test per the acceptance criterion: `ap_chat.identity_map.add_entry` writes
    the row (as the console provisioning flow does), and the real `IdentityAllowlist` - not a fake
    - picks it up via the runner's reload-on-miss, with no restart of the allowlist object."""
    import json

    from ap_chat.identity_map import IdentityAllowlist, add_entry

    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({}))
    identity_map = IdentityAllowlist(path)
    assert identity_map.resolve("321") is None  # not provisioned yet

    # Simulate the console's provisioning flow writing the allowlist row after the bot process
    # already loaded an empty map at startup.
    add_entry(path, "321", fathm_user_id="planner.newly-provisioned", token="tok-fresh")

    answer = ChatAnswer(answer="ok", refused=False, citations=())
    platform = FakePlatform([[[_msg(user="321")]]])
    manager_client = FakeManagerClient(answer=answer)
    runner = BotRunner(platform=platform, identity_map=identity_map, manager_client=manager_client, sleep=lambda s: None)
    runner.run_forever(max_poll_cycles=1)

    assert manager_client.calls == [(_msg(user="321").text, "tok-fresh")]
    assert runner.stats.messages_handled == 1
    assert identity_map.resolve("321").fathm_user_id == "planner.newly-provisioned"
