"""The self-hosted lip-sync stub: an open model on our own GPU.

LatentSync (ByteDance, Apache-2.0 code and weights) is the open model
LIPSYNC.md would self-host; MuseTalk would fit the same seam. It runs as a
small HTTP service we would deploy (a GPU box, not this server): POST the
window's video and audio as multipart to `{url}/sync`, get the synced video
back as the body. Off unless `AVE_LIPSYNC_PROVIDER=selfhosted` AND
`LIPSYNC_SELFHOSTED_URL` are both set. Cost is the GPU's time, so it is
priced per second from `LIPSYNC_SELFHOSTED_USD_PER_SECOND` (default 0).
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.lipsync.provider import LipSyncUnavailable, SpanRequest, SpanResult

TIMEOUT = 600.0   # a diffusion model takes many seconds per second of video


class SelfHostedLipSyncProvider:
    name = "selfhosted"

    def __init__(self, url: str | None, token: str | None = None, usd_per_second: float = 0.0,
                 switched_on: bool = False, http: httpx.Client | None = None) -> None:
        self._url = (url or "").rstrip("/") or None
        self._token = token or None
        self._usd = usd_per_second
        self._on = switched_on
        self._http = http

    @classmethod
    def from_env(cls) -> "SelfHostedLipSyncProvider":
        try:
            usd = float(os.environ.get("LIPSYNC_SELFHOSTED_USD_PER_SECOND") or 0)
        except ValueError:
            usd = 0.0
        return cls(os.environ.get("LIPSYNC_SELFHOSTED_URL"), os.environ.get("LIPSYNC_SELFHOSTED_TOKEN"), usd,
                   switched_on=(os.environ.get("AVE_LIPSYNC_PROVIDER") or "").strip().lower() == cls.name)

    def available(self) -> bool:
        return bool(self._url) and self._on

    def usd_for(self, seconds: float) -> float:
        return round(self._usd * seconds, 4)

    def sync_span(self, request: SpanRequest, dest: Path) -> SpanResult:
        if not self.available():
            raise LipSyncUnavailable("Self-hosted lip-sync is off.")
        http = self._http or httpx.Client(timeout=TIMEOUT)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        with open(request.clip, "rb") as video, open(request.audio, "rb") as audio:
            try:
                response = http.post(f"{self._url}/sync", headers=headers, files={
                    "video": ("window.mp4", video, "video/mp4"), "audio": ("window.wav", audio, "audio/wav"),
                })
            except httpx.HTTPError as exc:
                raise LipSyncUnavailable(f"The lip-sync server could not be reached ({type(exc).__name__}).") from None
        if response.status_code != 200:
            raise LipSyncUnavailable(f"The lip-sync server refused the clip ({response.status_code}).")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return SpanResult(dest, self.name, self.usd_for(request.seconds))
