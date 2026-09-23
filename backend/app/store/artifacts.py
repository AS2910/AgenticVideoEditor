"""Content-addressed media storage.

Layout: `<root>/<project_id>/<sha256>.<container>`

Addressing by the hash of the bytes means identical generation output lands on
one file no matter how many times it is produced, and an artifact's identity is
comparable across processes — which the opaque `audio://` strings never were.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from app.domain.models import MediaArtifact

_CHUNK = 1 << 20  # 1 MiB; video files get large from Phase 1 onward
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _dest(self, project_id: str, sha256: str, container: str) -> Path:
        return self.root / project_id / f"{sha256}.{container}"

    def _commit(self, project_id: str, sha256: str, kind: str, container: str,
                duration: float, write) -> MediaArtifact:
        dest = self._dest(project_id, sha256, container)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            # Write to a temp name and rename, so a crash mid-write can never
            # leave a truncated file sitting at a valid content address.
            tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
            write(tmp)
            tmp.replace(dest)
        return MediaArtifact(
            kind=kind, sha256=sha256, path=str(dest.resolve()),
            duration=duration, container=container,
        )

    def put_bytes(self, project_id: str, data: bytes, *, kind: str,
                  container: str, duration: float) -> MediaArtifact:
        sha256 = hashlib.sha256(data).hexdigest()
        return self._commit(
            project_id, sha256, kind, container, duration,
            lambda tmp: tmp.write_bytes(data),
        )

    def put_file(self, project_id: str, src: str | Path, *, kind: str,
                 container: str, duration: float) -> MediaArtifact:
        """Adopt a file produced elsewhere (e.g. an ffmpeg temp output)."""
        src = Path(src)
        sha256 = _hash_file(src)
        return self._commit(
            project_id, sha256, kind, container, duration,
            lambda tmp: tmp.write_bytes(src.read_bytes()),
        )

    def exists(self, artifact: MediaArtifact) -> bool:
        return Path(artifact.path).is_file()

    def find(self, project_id: str, sha256: str) -> Path | None:
        """Locate a stored artifact by content address, whatever its container.

        `sha256` arrives from the URL, so it is validated as a bare hex digest
        rather than trusted — otherwise it would be a path-traversal hole.
        """
        if not _HEX64.fullmatch(sha256):
            return None
        matches = sorted((self.root / project_id).glob(f"{sha256}.*"))
        for match in matches:
            if match.is_file() and not match.name.endswith(".tmp"):
                return match
        return None
