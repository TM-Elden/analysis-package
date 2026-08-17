"""NC.2 remote-capable publish path: `POST /packages/upload`.

Lets an agent harness that isn't running on the store host publish a package - the design report's
(`data/fathm-native-chat-readiness/report.md` §5.2 in the firstmate repo) "upload step ahead of
these endpoints, not change any endpoint shape" note from `ap_api/app.py`'s original phase-2 scope
comment, now built. The uploaded body is the exact same deterministic gzip-compressed tar shape
`ap_store.blobstore.make_blob` produces (a package directory packed with no wrapping directory) -
this endpoint does not invent a new archive format, it accepts the one that already exists.

**This is a review-blocking security surface** (the design report's risk note: "an authenticated
upload that unpacks archives is a classic path-traversal/zip-bomb surface"), so unpacking goes
through `ap_store.blobstore.extract_tar_gz` - the same containment discipline
(`ap_gate.checks.pathsafe.resolve_contained`) every manifest-path-resolving check and
`BlobStore.extract` already use, applied here to untrusted archive bytes for the first time, plus
two caps neither of those callers needed: a raw-body size cap (checked against `Content-Length`
before the body is even read, and again against the read body) and a declared-uncompressed-size
cap (checked from the tar's own member sizes before any member is extracted) - the zip-bomb half of
the risk note. A rejected archive is unpacked into a scratch directory that is discarded whole
(`tempfile.TemporaryDirectory`), never touching the real store.

Once safely unpacked, this calls `PackageStore.publish` unchanged - the exact function
`POST /packages` and every other publish path in the codebase uses. Bearer-token auth + the
`analyst` role, same `require_any_role`/`identity_from_request` machinery as every other
write route - no new auth model.
"""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ap_api.deps import get_store, require_any_role
from ap_api.schemas import PackageOut, package_record_to_out
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_store.blobstore import ArchiveContainmentError, ArchiveTooLargeError, extract_tar_gz
from ap_store.store import ImmutabilityError, PackageStore, StoreError

router = APIRouter()

#: Raw upload body cap - checked against Content-Length before the body is read, and again against
#: the bytes actually read (a caller can omit or lie about Content-Length). Overridable for
#: deployments with legitimately larger packages; the default is generous for this corpus's scale
#: (see CLAUDE.md's ap_index sizing note - packages are ~10^4 tokens, nowhere near this).
MAX_UPLOAD_BYTES = int(os.environ.get("AP_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))

#: Declared-uncompressed-size cap - the zip-bomb guard. Checked from the tar's own member sizes
#: before any member is extracted, independent of the compressed body cap above.
MAX_UPLOAD_UNCOMPRESSED_BYTES = int(os.environ.get("AP_UPLOAD_MAX_UNCOMPRESSED_BYTES", str(200 * 1024 * 1024)))


@router.post("/packages/upload", response_model=PackageOut, status_code=201)
async def upload_package(
    request: Request,
    actor: Annotated[Identity, Depends(require_any_role(Role.ANALYST))],
    store: Annotated[PackageStore, Depends(get_store)],
) -> PackageOut:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"upload exceeds the {MAX_UPLOAD_BYTES} byte cap (Content-Length: {declared_length})")

    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"upload exceeds the {MAX_UPLOAD_BYTES} byte cap ({len(body)} bytes read)")

    with tempfile.TemporaryDirectory(prefix="ap-upload-") as scratch:
        scratch_dir = Path(scratch) / "package"
        try:
            extract_tar_gz(body, scratch_dir, max_uncompressed_bytes=MAX_UPLOAD_UNCOMPRESSED_BYTES)
        except ArchiveTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (ArchiveContainmentError, tarfile.TarError, OSError, EOFError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid or unsafe archive: {exc}") from exc

        try:
            record = store.publish(scratch_dir, actor=actor)
        except ImmutabilityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return package_record_to_out(record)
