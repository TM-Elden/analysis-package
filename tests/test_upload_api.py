"""NC.2 remote-capable publish path: `POST /packages/upload` - see ap_api/upload_routes.py and
CLAUDE.md's NC.2 section.

Same `base_url="https://testserver"` requirement as tests/test_api.py (the Secure session cookie);
these tests all use bearer tokens instead, but the fixture is shared for consistency.
"""

from __future__ import annotations

import gzip
import io
import tarfile

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
import ap_api.upload_routes as upload_routes
from ap_agent_tools.tools import package_create
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_store.blobstore import make_blob
from ap_store.store import PackageStore


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password=None)
    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password=None)

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, auth_store, tmp_path
    finally:
        app.dependency_overrides.clear()
        store.close()
        auth_store.close()


def _bearer(auth_store: AuthStore, user_id: str) -> dict:
    token = auth_store.create_service_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _tar_gz(entries: dict[str, bytes | None]) -> bytes:
    """Build a tar.gz from {member_name: content}; content=None writes a directory entry."""
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        for name, content in entries.items():
            if content is None:
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
        gz.write(tar_buf.getvalue())
    return gz_buf.getvalue()


def test_upload_publishes_a_real_package(client_and_store):
    client, store, auth_store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="Uploaded pack", analyst_id="tom.analyst")
    blob = make_blob(pkg_dir)

    r = client.post(
        "/packages/upload",
        content=blob,
        headers={**_bearer(auth_store, "tom.analyst"), "Content-Type": "application/gzip"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["published_by_id"] == "tom.analyst"

    record = store.get(body["package_id"], body["package_version"])
    assert record is not None


def test_upload_requires_analyst_role(client_and_store):
    client, _store, auth_store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="Uploaded pack", analyst_id="tom.analyst")
    blob = make_blob(pkg_dir)

    r = client.post("/packages/upload", content=blob, headers=_bearer(auth_store, "ro.reader"))
    assert r.status_code == 403


def test_upload_requires_authentication(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="Uploaded pack", analyst_id="tom.analyst")
    blob = make_blob(pkg_dir)

    r = client.post("/packages/upload", content=blob)
    assert r.status_code == 401


def test_upload_rejects_path_traversal_entry_before_unpack(client_and_store):
    """A crafted archive with a `../` entry must be rejected before any member is extracted - no
    file should land outside the scratch dir. We can't inspect the (discarded) scratch dir
    directly, so the real assertion is: the request is rejected (400), and the store never
    receives a published package as a result."""
    client, store, auth_store, _tmp_path = client_and_store
    evil = _tar_gz({"../escaped.txt": b"pwned"})

    r = client.post("/packages/upload", content=evil, headers=_bearer(auth_store, "tom.analyst"))
    assert r.status_code == 400, r.text
    assert "escapes" in r.json()["detail"]
    assert store.list().total == 0


def test_upload_rejects_absolute_path_entry_before_unpack(client_and_store):
    client, store, auth_store, _tmp_path = client_and_store
    evil = _tar_gz({"/etc/evil.txt": b"pwned"})

    r = client.post("/packages/upload", content=evil, headers=_bearer(auth_store, "tom.analyst"))
    assert r.status_code == 400, r.text
    assert store.list().total == 0


def test_upload_rejects_symlink_entry(client_and_store):
    """Not just name-containment: a symlink member (even with an in-bounds *name*) could point its
    target outside the destination on extraction - rejected by member-type restriction."""
    client, store, auth_store, _tmp_path = client_and_store
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        info = tarfile.TarInfo(name="MANIFEST.yaml")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
        gz.write(tar_buf.getvalue())
    evil = gz_buf.getvalue()

    r = client.post("/packages/upload", content=evil, headers=_bearer(auth_store, "tom.analyst"))
    assert r.status_code == 400, r.text
    assert store.list().total == 0


def test_upload_rejects_oversized_archive_before_full_unpack(client_and_store, monkeypatch):
    """Declared-uncompressed-size cap - the zip-bomb guard. A tiny compressed body can still
    declare a huge uncompressed size; the cap must be checked (and the archive rejected) from the
    tar's own member metadata before any member is extracted."""
    client, store, auth_store, _tmp_path = client_and_store
    monkeypatch.setattr(upload_routes, "MAX_UPLOAD_UNCOMPRESSED_BYTES", 1024)

    # A single member declaring far more bytes than actually follow in the tar stream - this is
    # what a real zip bomb looks like: tiny on the wire, huge once unpacked. tarfile reads member
    # *sizes* from the header without needing the declared bytes to actually be present for
    # getmembers() to see them, so the cap check (which only reads headers) catches it before
    # extractall() would ever try to write real bytes.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        info = tarfile.TarInfo(name="bomb.bin")
        info.size = 10 * 1024 * 1024  # 10MB declared, cap is 1KB
        tar.addfile(info, io.BytesIO(b"\0" * info.size))
    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
        gz.write(tar_buf.getvalue())
    bomb = gz_buf.getvalue()

    r = client.post("/packages/upload", content=bomb, headers=_bearer(auth_store, "tom.analyst"))
    assert r.status_code == 413, r.text
    assert store.list().total == 0


def test_upload_rejects_oversized_raw_body_via_content_length(client_and_store, monkeypatch):
    """The compressed-body cap, independent of the uncompressed-size cap above - checked against
    Content-Length before the body is even read."""
    client, store, auth_store, tmp_path = client_and_store
    monkeypatch.setattr(upload_routes, "MAX_UPLOAD_BYTES", 16)

    pkg_dir = package_create(tmp_path / "pkg", title="Uploaded pack", analyst_id="tom.analyst")
    blob = make_blob(pkg_dir)
    assert len(blob) > 16

    r = client.post("/packages/upload", content=blob, headers=_bearer(auth_store, "tom.analyst"))
    assert r.status_code == 413, r.text
    assert store.list().total == 0


def test_upload_republishing_same_bytes_is_idempotent(client_and_store):
    client, store, auth_store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="Uploaded pack", analyst_id="tom.analyst")
    blob = make_blob(pkg_dir)
    headers = _bearer(auth_store, "tom.analyst")

    r1 = client.post("/packages/upload", content=blob, headers=headers)
    r2 = client.post("/packages/upload", content=blob, headers=headers)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["package_version"] == r2.json()["package_version"]
    assert store.list().total == 1
