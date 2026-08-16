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

    def extract(self, sha256: str, dest_dir: Path) -> None:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(fileobj=io.BytesIO(self.get(sha256)), mode="rb") as gz:
            tar_bytes = gz.read()
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            for member in tar.getmembers():
                if resolve_contained(dest_dir, member.name) is None:
                    raise ValueError(f"blob member {member.name!r} escapes the extraction directory")
            # "data" filter (py3.12+) is redundant given the containment check above (our own
            # make_blob() only ever writes plain files with fixed mode/uid/gid) but silences the
            # extractall() DeprecationWarning on those versions without breaking py3.10/3.11.
            data_filter = getattr(tarfile, "data_filter", None)
            if data_filter is not None:
                tar.extractall(dest_dir, filter=data_filter)
            else:
                tar.extractall(dest_dir)
