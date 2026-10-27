"""The mouth, by sync.so (Phase 17a).

sync.so re-draws a speaker's mouth to match new audio. It takes a video and an
audio file and returns the video with the mouth moved. Local files go up as
assets (a presigned PUT), the job is created, polled until it finishes, and the
result downloaded. It is billed by the second of video, so callers send only
the stretches that have a face.

This module is the vendor client only: it knows nothing of edits or shots.
`render/mouth.py` decides what to send and where the result goes.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import httpx

from app.adapters.base import VendorError
from app.errors import NonRetryableError

BASE = "https://api.sync.so"
DEFAULT_MODEL = "lipsync-2"
MODELS = ("lipsync-2", "sync-3", "lipsync-2-pro")
POLL_EVERY = 3.0          # seconds between status checks
POLL_FOR = 900.0          # give up on a job after this long (the runner retries a VendorError)
DEFAULT_TIMEOUT = 60.0


class MouthError(VendorError):
    """sync.so is down, slow or rate-limited: worth trying again."""


class MouthConfigError(NonRetryableError):
    """sync.so refused the request itself: the key, the plan's allowance, or the input."""


class MouthRefused(NonRetryableError):
    """sync.so looked at the clip and could not do it (no face it could use, too short)."""

    def __init__(self, code: str | None, message: str | None) -> None:
        self.code = code
        super().__init__(message or "sync.so could not move the mouth in this clip.")


def _raise_for(status: int, text: str, key: str) -> None:
    text = text.replace(key, "***")
    if status == 429 or status >= 500:
        raise MouthError(f"sync.so is unavailable right now ({status}).")
    if status in (401, 403):
        raise MouthConfigError(f"sync.so rejected the API key ({status}). Check SYNC_API_KEY.")
    if status == 402 or "credit" in text.lower() or "quota" in text.lower():
        raise MouthConfigError("The sync.so plan has no credit left for this clip.")
    raise MouthConfigError(f"sync.so refused the request ({status}): {text[:200]}")


class SyncSoClient:
    def __init__(
        self, api_key: str, *, http: httpx.Client | None = None, timeout: float = DEFAULT_TIMEOUT,
        poll_every: float = POLL_EVERY, poll_for: float = POLL_FOR,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key = api_key
        self._http = http or httpx.Client(timeout=timeout)
        self._poll_every, self._poll_for = poll_every, poll_for
        self._sleep, self._clock = sleep, clock

    def _call(self, method: str, path: str, **kw) -> dict | list:
        try:
            response = self._http.request(method, BASE + path, headers={"x-api-key": self._key}, **kw)
        except httpx.HTTPError as exc:
            # The exception text is dropped: transport errors can echo request details.
            raise MouthError(f"Could not reach sync.so ({type(exc).__name__}).") from None
        if response.status_code not in (200, 201):
            _raise_for(response.status_code, response.text, self._key)
        try:
            return response.json()
        except ValueError:
            raise MouthError("sync.so answered with something that was not JSON.") from None

    def upload(self, path: Path, content_type: str, kind: str) -> dict:
        """A local file as an asset; returns the generate-input fields for it
        (`assetId` when sync.so gave one, else the registered `url`)."""
        data = Path(path).read_bytes()
        slot = self._call("POST", "/v2/assets/upload", json={
            "fileName": Path(path).name, "contentType": content_type, "size": len(data),
        })
        try:
            put = self._http.put(slot["uploadUrl"], content=data, headers={"Content-Type": content_type})
        except httpx.HTTPError as exc:
            raise MouthError(f"Could not upload to sync.so ({type(exc).__name__}).") from None
        if put.status_code not in (200, 201, 204):
            raise MouthError(f"sync.so's storage refused the upload ({put.status_code}).")
        asset = self._call("POST", "/v2/assets", json={
            "url": slot["url"], "type": kind.upper(), "name": Path(path).name,
        })
        asset_id = asset.get("id") if isinstance(asset, dict) else None
        return {"assetId": asset_id} if asset_id else {"url": slot["url"]}

    def estimate(self, model: str, seconds: float) -> float | None:
        """What `seconds` of video costs on `model`, in USD, as sync.so prices
        it; None when it will not say."""
        try:
            answer = self._call("POST", "/v2/generations/estimate", json={"model": model, "duration": seconds})
        except (MouthError, MouthConfigError):
            return None
        cost = answer.get("estimatedGenerationCost") if isinstance(answer, dict) else None
        return float(cost) if isinstance(cost, (int, float)) else None

    def generate(self, body: dict) -> str:
        job = self._call("POST", "/v2/generate", json=body)
        return str(job["id"])

    def wait(self, job_id: str) -> dict:
        """Poll until the job reaches a terminal state; a refusal raises."""
        deadline = self._clock() + self._poll_for
        while True:
            job = self._call("GET", f"/v2/generate/{job_id}")
            status = job.get("status")
            if status == "COMPLETED":
                return job
            if status in ("FAILED", "REJECTED"):
                raise MouthRefused(job.get("errorCode"), job.get("error"))
            if self._clock() >= deadline:
                raise MouthError("sync.so is taking too long on this clip.")
            self._sleep(self._poll_every)

    def download(self, url: str, dest: Path) -> Path:
        try:
            response = self._http.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise MouthError(f"Could not download from sync.so ({type(exc).__name__}).") from None
        if response.status_code != 200:
            raise MouthError(f"sync.so's result could not be downloaded ({response.status_code}).")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return dest

    def move_mouth(
        self, video: Path, audio: Path, dest: Path, *, model: str = DEFAULT_MODEL,
        options: dict | None = None,
    ) -> tuple[Path, dict]:
        """Video + audio in, the video with its mouth moved out (written to
        `dest`). Returns the path and sync.so's finished-job record."""
        body = {
            "model": model,
            "input": [
                {"type": "video", **self.upload(video, "video/mp4", "video")},
                {"type": "audio", **self.upload(audio, "audio/wav", "audio")},
            ],
            "options": {"sync_mode": "cut_off", **(options or {})},
        }
        job = self.wait(self.generate(body))
        return self.download(job["outputUrl"], dest), job
