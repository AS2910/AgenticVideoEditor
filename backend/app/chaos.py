"""Fault injection for game days (the chaos pass, 2026-10-10).

Voltage runs as one process talking to three paid vendors over HTTPS, so the
failures worth rehearsing are a vendor that rate-limits, hangs, resets the
connection or just gets slow. `AVE_CHAOS` injects those at the adapters' own
seams — the `post` callables and the Anthropic client — without touching the
network, so nothing is charged and nothing leaves the machine.

    AVE_CHAOS="elevenlabs=status:429@0.5;anthropic=hang:120;openai=reset"

One fault per vendor, `kind[:arg][@rate]`:
- `status:<code>`  the vendor answers with that HTTP status (ElevenLabs/OpenAI)
                   or an APIStatusError (Anthropic)
- `hang:<seconds>` the call blocks that long, then fails as a timeout
- `slow:<seconds>` the call takes that long, then succeeds
- `reset`          the connection drops (a transport error)
`@rate` is the share of calls hit (default 1.0: every call).

Blast radius: this process only, and never with sign-in on (a public
deployment) unless `AVE_CHAOS_FORCE=1` says so. Rollback: unset the variable
and restart — under `uvicorn --reload` that is one `touch` of any file.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

VENDORS = ("elevenlabs", "openai", "anthropic")
KINDS = ("status", "hang", "slow", "reset")


@dataclass(frozen=True)
class Fault:
    vendor: str
    kind: str
    arg: float = 0.0
    rate: float = 1.0

    def hits(self, rng: random.Random) -> bool:
        return self.rate >= 1.0 or rng.random() < self.rate


def parse(spec: str | None) -> dict[str, Fault]:
    """`vendor=kind[:arg][@rate]` entries separated by `;`. Bad specs raise ValueError."""
    faults: dict[str, Fault] = {}
    for entry in (spec or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"AVE_CHAOS entry {entry!r} needs vendor=kind")
        vendor, rest = (p.strip() for p in entry.split("=", 1))
        if vendor not in VENDORS:
            raise ValueError(f"AVE_CHAOS vendor {vendor!r} is not one of {VENDORS}")
        rate = 1.0
        if "@" in rest:
            rest, rate_text = rest.rsplit("@", 1)
            rate = float(rate_text)
            if not 0.0 < rate <= 1.0:
                raise ValueError(f"AVE_CHAOS rate {rate} must be in (0, 1]")
        kind, _, arg_text = rest.partition(":")
        if kind not in KINDS:
            raise ValueError(f"AVE_CHAOS kind {kind!r} is not one of {KINDS}")
        arg = float(arg_text) if arg_text else 0.0
        if kind == "status" and not arg_text:
            raise ValueError("AVE_CHAOS status needs a code, e.g. status:429")
        if kind in ("hang", "slow") and arg <= 0:
            raise ValueError(f"AVE_CHAOS {kind} needs seconds, e.g. {kind}:30")
        faults[vendor] = Fault(vendor, kind, arg, rate)
    return faults


def allowed(auth_mode: str, force: bool) -> bool:
    """Chaos never runs where people are signed in, unless forced."""
    return auth_mode == "off" or force


class Chaos:
    """The faults in force, and the wrappers that apply them."""

    def __init__(self, faults: dict[str, Fault], sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None) -> None:
        self.faults = faults
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.hits: dict[str, int] = {v: 0 for v in faults}

    def describe(self) -> str | None:
        if not self.faults:
            return None
        return ";".join(f"{f.vendor}={f.kind}" + (f":{f.arg:g}" if f.arg else "") + (f"@{f.rate:g}" if f.rate < 1 else "")
                        for f in self.faults.values())

    def _fault(self, vendor: str) -> Fault | None:
        f = self.faults.get(vendor)
        if f is None or not f.hits(self._rng):
            return None
        self.hits[vendor] += 1
        log.warning("CHAOS: %s %s%s", vendor, f.kind, f":{f.arg:g}" if f.arg else "")
        return f

    # ── ElevenLabs: post(voice_id, body, api_key, timeout) -> (status, bytes, text) ──
    def elevenlabs_post(self, post):
        def wrapped(voice_id, body, api_key, timeout):
            f = self._fault("elevenlabs")
            if f is None:
                return post(voice_id, body, api_key, timeout)
            if f.kind == "status":
                return int(f.arg), b"", f'{{"detail": "chaos: injected {int(f.arg)}"}}'
            if f.kind == "hang":
                self._sleep(f.arg)
                from app.adapters.elevenlabs import VoiceError
                raise VoiceError("Could not reach ElevenLabs (ReadTimeout).")
            if f.kind == "slow":
                self._sleep(f.arg)
                return post(voice_id, body, api_key, timeout)
            from app.adapters.elevenlabs import VoiceError
            raise VoiceError("Could not reach ElevenLabs (ConnectError).")
        return wrapped

    # ── OpenAI: post(audio_path, api_key, timeout) -> dict ──
    def openai_post(self, post):
        def wrapped(audio_path: Path, api_key: str, timeout: float) -> dict:
            f = self._fault("openai")
            if f is None:
                return post(audio_path, api_key, timeout)
            from app.adapters.openai_whisper import TranscriptionError
            if f.kind == "status":
                raise TranscriptionError(f"OpenAI transcription failed ({int(f.arg)}): chaos")
            if f.kind == "hang":
                self._sleep(f.arg)
                raise TranscriptionError("OpenAI transcription failed (timeout): chaos")
            if f.kind == "slow":
                self._sleep(f.arg)
                return post(audio_path, api_key, timeout)
            raise TranscriptionError("OpenAI transcription failed (connection reset): chaos")
        return wrapped

    # ── Anthropic: a client whose messages.parse may fail ──
    def anthropic_client(self, client):
        return _ChaosAnthropic(client, self)


class _ChaosMessages:
    def __init__(self, inner, chaos: Chaos) -> None:
        self._inner = inner
        self._chaos = chaos

    def parse(self, *args, **kwargs):
        f = self._chaos._fault("anthropic")
        if f is None:
            return self._inner.parse(*args, **kwargs)
        import anthropic
        import httpx
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        if f.kind == "status":
            response = httpx.Response(int(f.arg), request=request, text="chaos")
            if int(f.arg) == 429:
                raise anthropic.RateLimitError("chaos: injected 429", response=response, body=None)
            if int(f.arg) >= 500:
                raise anthropic.InternalServerError("chaos: injected 5xx", response=response, body=None)
            raise anthropic.APIStatusError(f"chaos: injected {int(f.arg)}", response=response, body=None)
        if f.kind == "hang":
            self._chaos._sleep(f.arg)
            raise anthropic.APITimeoutError(request=request)
        if f.kind == "slow":
            self._chaos._sleep(f.arg)
            return self._inner.parse(*args, **kwargs)
        raise anthropic.APIConnectionError(message="chaos: connection reset", request=request)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _ChaosAnthropic:
    def __init__(self, inner, chaos: Chaos) -> None:
        self._inner = inner
        self.messages = _ChaosMessages(inner.messages, chaos)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def from_settings(spec: str | None, auth_mode: str, force: bool) -> Chaos | None:
    """The process's chaos, or None. Refuses, loudly, where it must not run."""
    faults = parse(spec)
    if not faults:
        return None
    if not allowed(auth_mode, force):
        log.error("AVE_CHAOS is set but sign-in is on; refusing to inject faults (set AVE_CHAOS_FORCE=1 to insist)")
        return None
    chaos = Chaos(faults)
    log.warning("CHAOS ON: %s — nothing is charged for an injected fault; unset AVE_CHAOS to stop", chaos.describe())
    return chaos
