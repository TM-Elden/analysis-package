"""Content-addressed blob storage for package bytes (C3).

A package directory is packed into a deterministic gzip-compressed tar (fixed member order, zeroed
mtimes/uid/gid so identical file content always produces identical bytes regardless of when or in
what order files were written) and stored under its sha256. Content addressing is what makes
immutability free: the same `(package_id, package_version)` republished with identical bytes always
lands on the same blob path, and PackageStore.publish() treats that as a no-op rather than an error.

Extraction reuses `ap_gate.checks.pathsafe.resolve_contained` to validate every archive member stays
under the destination directory before extracting - the same path-containment discipline every
manifest-path-resolving ap-gate check already applies, now applied to blob members too.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path

from ap_gate.checks.pathsafe import resolve_contained


class ArchiveError(Exception):
    """Base for a rejected tar.gz archive - never partially extracted (see extract_tar_gz)."""


class ArchiveTooLargeError(ArchiveError):
    """The archive's declared uncompressed size exceeds a caller-supplied cap - raised before any
    member is extracted, so a zip-bomb-style archive (small compressed body, huge decompressed
    content) never touches disk."""


class ArchiveContainmentError(ArchiveError):
    """A member's name would resolve outside the destination directory (absolute path or `..`
    traversal - the resolve_contained discipline), or is not a plain file/directory (a symlink or
    hardlink could otherwise point outside the destination) - raised before any member is
    extracted."""


def extract_tar_gz(data: bytes, dest_dir: Path, *, max_uncompressed_bytes: int | None = None) -> None:
    """Safely extract gzip-compressed tar bytes into dest_dir.

    Decompression itself is bounded, not just its output: the gzip stream is read in fixed-size
    chunks and max_uncompressed_bytes is enforced against the running decompressed total as each
    chunk arrives, so a highly-compressible zip-bomb-style archive is aborted mid-decompression
    instead of first being fully materialized in memory. Every member is then also validated
    *before* any extraction happens (containment via ap_gate.checks.pathsafe.resolve_contained,
    applied to raw archive bytes exactly as it's applied to manifest-declared paths elsewhere;
    member type restricted to plain files/directories; total declared size checked against
    max_uncompressed_bytes if given, as a second, cheap check against the tar headers) - a rejected
    archive leaves dest_dir empty, never a partial unpack. Shared by BlobStore.extract (our own
    trusted, self-produced blobs - no cap) and ap_api's upload endpoint (untrusted planner-
    submitted archives - cap enforced, see CLAUDE.md's NC.2 section).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = 1024 * 1024
    tar_buf = io.BytesIO()
    total_decompressed = 0
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
        while True:
            chunk = gz.read(chunk_size)
            if not chunk:
                break
            total_decompressed += len(chunk)
            if max_uncompressed_bytes is not None and total_decompressed > max_uncompressed_bytes:
                raise ArchiveTooLargeError(
                    f"archive decompresses to more than the {max_uncompressed_bytes} byte cap"
                )
            tar_buf.write(chunk)
    tar_bytes = tar_buf.getvalue()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        members = tar.getmembers()

        if max_uncompressed_bytes is not None:
            total = sum(m.size for m in members)
            if total > max_uncompressed_bytes:
                raise ArchiveTooLargeError(
                    f"archive declares {total} bytes uncompressed, exceeding the {max_uncompressed_bytes} byte cap"
                )

        for member in members:
            if resolve_contained(dest_dir, member.name) is None:
                raise ArchiveContainmentError(f"archive member {member.name!r} escapes the extraction directory")
            if not (member.isfile() or member.isdir()):
                raise ArchiveContainmentError(
                    f"archive member {member.name!r} is not a plain file or directory (type {member.type!r}) - rejected"
                )

        # "data" filter (py3.12+) is redundant given the containment/type checks above but silences
        # the extractall() DeprecationWarning on those versions without breaking py3.10/3.11.
        data_filter = getattr(tarfile, "data_filter", None)
        if data_filter is not None:
            tar.extractall(dest_dir, filter=data_filter)
        else:
            tar.extractall(dest_dir)


def _iter_files(pkg_dir: Path):
    for p in sorted(pkg_dir.rglob("*")):
        if p.is_file():
            yield p


def make_blob(pkg_dir: Path) -> bytes:
    """Deterministically pack a package directory into gzip-compressed tar bytes."""
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in _iter_files(pkg_dir):
            data = f.read_bytes()
            info = tarfile.TarInfo(name=str(f.relative_to(pkg_dir)))
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))

    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb", mtime=0) as gz:
        gz.write(tar_buf.getvalue())
    return gz_buf.getvalue()


def blob_sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class BlobStore:
    """Shards blobs by the first two hex chars of their sha256 under `root`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sha256: str) -> Path:
        return self.root / sha256[:2] / f"{sha256}.tar.gz"

    def has(self, sha256: str) -> bool:
        return self._path_for(sha256).is_file()

    def put(self, blob: bytes, sha256: str) -> Path:
        path = self._path_for(sha256)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(blob)
            tmp.replace(path)  # atomic within the same filesystem
        return path

    def get(self, sha256: str) -> bytes:
        return self._path_for(sha256).read_bytes()

    def delete(self, sha256: str) -> None:
        """Unlink a blob's bytes. Callers (PackageStore.purge) must refcount against every
        non-purged `packages` row sharing this `blob_sha256` before calling - blobs are
        content-addressed and shared across (package_id, package_version) pairs, so this method
        itself has no notion of "is anyone else still using this" and trusts the caller."""
        path = self._path_for(sha256)
        if path.is_file():
            path.unlink()

    def extract(self, sha256: str, dest_dir: Path) -> None:
        """No size cap here - these are our own deterministically-produced blobs (make_blob only
        ever writes plain files), not untrusted uploads; see extract_tar_gz's docstring."""
        try:
            extract_tar_gz(self.get(sha256), dest_dir)
        except ArchiveContainmentError as exc:
            raise ValueError(str(exc)) from exc  # preserve extract()'s pre-existing exception type
