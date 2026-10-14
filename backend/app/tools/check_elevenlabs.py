"""What this ElevenLabs key can do, before Voltage depends on it (Phase 15a).

    python -m app.tools.check_elevenlabs

A key made with limited access answers 401 and names the permission it lacks.
This asks for each thing Voltage uses, once, with read-only calls that spend no
credits, and prints a line per capability. It never prints the key.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Callable

import httpx

from app.config import load_settings

BASE = "https://api.elevenlabs.io"
_MISSING = re.compile(r"missing the permission (\w+)")

# (what Voltage does with it, the permission it needs, a read-only way to ask)
PROBES = [
    ("Know the plan and what is left of it", "user_read", "/v1/user/subscription"),
    ("List the voices to speak in", "voices_read", "/v2/voices?page_size=1"),
    ("Know each model's cost", "models_read", "/v1/models"),
]
# Permissions that cannot be tested without spending or changing something.
UNTESTED = [
    ("Speak a line", "text_to_speech"),
    ("Make a clone of a speaker", "voices_write"),
    ("Voice Changer (speech to speech)", "speech_to_speech"),
]

Get = Callable[[str, str], tuple[int, str, dict | None]]


@dataclass(frozen=True)
class Finding:
    what: str
    permission: str
    ok: bool
    detail: str = ""


def _get(api_key: str, path: str) -> tuple[int, str, dict | None]:
    try:
        response = httpx.get(BASE + path, headers={"xi-api-key": api_key}, timeout=20.0)
    except httpx.HTTPError as exc:
        return 0, f"could not reach ElevenLabs ({type(exc).__name__})", None
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, response.text.replace(api_key, "***"), body


def check(api_key: str, get: Get = _get) -> tuple[list[Finding], dict]:
    """Findings per probe, and the subscription's own words when it could be read."""
    findings: list[Finding] = []
    plan: dict = {}
    for what, permission, path in PROBES:
        status, text, body = get(api_key, path)
        if status == 200:
            findings.append(Finding(what, permission, True))
            if permission == "user_read" and isinstance(body, dict):
                plan = body
            continue
        missing = _MISSING.search(text)
        detail = (f"the key lacks {missing.group(1)}" if missing
                  else "the key was rejected" if status in (401, 403)
                  else f"answered {status}" if status else text)
        findings.append(Finding(what, permission, False, detail))
    return findings, plan


def report(findings: list[Finding], plan: dict) -> str:
    lines = []
    for f in findings:
        lines.append(f"  {'ok  ' if f.ok else 'FAIL'} {f.what} ({f.permission})" + (f": {f.detail}" if f.detail else ""))
    for what, permission in UNTESTED:
        lines.append(f"  --   {what} ({permission}): not tested here — it spends credits or changes your account")
    if plan:
        lines.append("")
        lines.append(f"  Plan: {plan.get('tier', '?')} ({plan.get('status', '?')})")
        lines.append(f"  Characters: {plan.get('character_count', '?')} of {plan.get('character_limit', '?')} used")
        lines.append(f"  Instant voice cloning: {'yes' if plan.get('can_use_instant_voice_cloning') else 'NO'}")
        lines.append(f"  Voice slots: {plan.get('voice_slots_used', '?')} of {plan.get('voice_limit', '?')} used")
    failed = [f for f in findings if not f.ok]
    lines.append("")
    if failed:
        lines.append("Fix: ElevenLabs → Developers → API keys → edit the key and allow "
                     + ", ".join(sorted({f.permission for f in failed})) + " (or make it unrestricted).")
    else:
        lines.append("The key can do everything Voltage reads. Cloning is attempted on the first line of a speaker.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    key = load_settings().elevenlabs_api_key
    if not key:
        print("No ELEVENLABS_API_KEY in backend/.env — Voltage will use its offline mock voice.")
        return 1
    findings, plan = check(key)
    print(report(findings, plan))
    return 0 if all(f.ok for f in findings) else 1


if __name__ == "__main__":
    sys.exit(main())
