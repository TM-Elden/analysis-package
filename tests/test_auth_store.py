"""C11 real auth: password hashing, AuthStore user/session/bearer-token lifecycle, CSRF derivation."""

from __future__ import annotations

import datetime as dt

import pytest

from ap_auth.csrf import csrf_token_for, csrf_token_matches
from ap_auth.passwords import hash_password, verify_password
from ap_auth.roles import Role
from ap_auth.store import AuthError, AuthStore


def test_hash_password_round_trips_and_rejects_wrong_password():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_hash_password_uses_a_fresh_salt_each_time():
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b


def test_verify_password_never_raises_on_garbage_hash():
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("anything", "")


def test_csrf_token_is_deterministic_and_bound_to_the_token():
    tok = "abc123"
    assert csrf_token_for(tok) == csrf_token_for(tok)
    assert csrf_token_for(tok) != csrf_token_for("different")
    assert csrf_token_matches(tok, csrf_token_for(tok))
    assert not csrf_token_matches(tok, "wrong")
    assert not csrf_token_matches(tok, None)


@pytest.fixture()
def auth_store(tmp_path):
    with AuthStore(tmp_path / "auth.sqlite3") as store:
        yield store


def test_create_user_and_verify_login(auth_store):
    auth_store.create_user(
        "tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="hunter2"
    )
    identity = auth_store.verify_login("tom.analyst", "hunter2")
    assert identity is not None
    assert identity.id == "tom.analyst"
    assert identity.roles == frozenset({Role.ANALYST})

    assert auth_store.verify_login("tom.analyst", "wrong") is None
    assert auth_store.verify_login("no.such.user", "hunter2") is None


def test_duplicate_user_raises(auth_store):
    auth_store.create_user("tom", display_name="Tom", roles=frozenset({Role.ANALYST}), password="x")
    with pytest.raises(AuthError):
        auth_store.create_user("tom", display_name="Tom 2", roles=frozenset({Role.ANALYST}), password="y")


def test_disabled_user_cannot_login_and_loses_active_sessions(auth_store):
    auth_store.create_user("jane", display_name="Jane", roles=frozenset({Role.REVIEWER}), password="pw")
    raw_session = auth_store.create_session("jane")
    assert auth_store.identity_for_token(raw_session) is not None

    auth_store.set_disabled("jane", True)

    assert auth_store.verify_login("jane", "pw") is None
    assert auth_store.identity_for_token(raw_session) is None  # revoked as a side effect of disabling


def test_set_password_updates_hash(auth_store):
    auth_store.create_user("tom", display_name="Tom", roles=frozenset({Role.ANALYST}), password="old")
    auth_store.set_password("tom", "new")
    assert auth_store.verify_login("tom", "old") is None
    assert auth_store.verify_login("tom", "new") is not None


def test_session_token_resolves_to_identity_and_revoke_kills_it(auth_store):
    auth_store.create_user("tom", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw")
    raw = auth_store.create_session("tom")
    identity = auth_store.identity_for_token(raw)
    assert identity is not None and identity.id == "tom"

    auth_store.revoke_token(raw)
    assert auth_store.identity_for_token(raw) is None


def test_expired_session_does_not_resolve(auth_store):
    auth_store.create_user("tom", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw")
    raw = auth_store.create_session("tom", ttl=dt.timedelta(seconds=-1))
    assert auth_store.identity_for_token(raw) is None


def test_service_bearer_token_resolves_like_a_session(auth_store):
    auth_store.create_user(
        "ci.bot", display_name="CI bot", roles=frozenset({Role.ANALYST}), password=None
    )
    raw = auth_store.create_service_token("ci.bot")
    identity = auth_store.identity_for_token(raw)
    assert identity is not None
    assert identity.id == "ci.bot"
    assert identity.roles == frozenset({Role.ANALYST})


def test_unknown_token_does_not_resolve(auth_store):
    assert auth_store.identity_for_token("not-a-real-token") is None


def test_list_users_reports_password_and_disabled_state(auth_store):
    auth_store.create_user("tom", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw")
    auth_store.create_user("ci.bot", display_name="CI", roles=frozenset({Role.ANALYST}), password=None)
    auth_store.set_disabled("tom", True)

    users = {u.id: u for u in auth_store.list_users()}
    assert users["tom"].disabled is True
    assert users["tom"].has_password is True
    assert users["ci.bot"].has_password is False
