"""The hosted lip-sync stub: sync.so, behind the provider seam.

The client (`adapters/sync_so.py`) was built and tested in Phase 17 and
measured in its spike (lipsync-2: $0.06 a second, about a minute for a 1.3 s
clip, picture size and frame rate kept). This wraps it as a `LipSyncProvider`.
It is off unless `AVE_LIPSYNC_PROVIDER=sync_so` AND `SYNC_API_KEY` are both
set: a key alone (the dev .env has one) never sends anything.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.lipsync.provider import LipSyncUnavailable, SpanRequest, SpanResult

USD_PER_SECOND = {"lipsync-2": 0.06, "lipsync-2-pro": 0.10, "sync-3": 0.16}


class SyncSoLipSyncProvider:
    name = "sync_so"

    def __init__(self, api_key: str | None, model: str = "lipsync-2", switched_on: bool = False, client=None) -> None:
        self._key = api_key or None
        self.model = model if model in USD_PER_SECOND else "lipsync-2"
        self._on = switched_on
        self._client = client

    @classmethod
    def from_env(cls) -> "SyncSoLipSyncProvider":
        return cls(os.environ.get("SYNC_API_KEY"), os.environ.get("AVE_LIPSYNC_MODEL") or "lipsync-2",
                   switched_on=(os.environ.get("AVE_LIPSYNC_PROVIDER") or "").strip().lower() == cls.name)

    def available(self) -> bool:
        return bool(self._key) and self._on

    def usd_for(self, seconds: float) -> float:
        return round(USD_PER_SECOND[self.model] * seconds, 4)

    def sync_span(self, request: SpanRequest, dest: Path) -> SpanResult:
        if not self.available():
            raise LipSyncUnavailable("Lip-sync by sync.so is off.")
        from app.adapters.sync_so import SyncSoClient
        client = self._client or SyncSoClient(self._key)
        path, job = client.move_mouth(request.clip, request.audio, dest, model=self.model)
        seconds = float(job.get("outputDuration") or request.seconds)
        return SpanResult(path, self.name, self.usd_for(seconds))
