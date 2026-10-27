"""The voice A/B listening page (run 5 item 7): trials from the voice tone eval, blind votes.

A run is a folder the eval writes (`python -m evals voice-tone`): `trials.json`
and, per trial, three short clips in context: the original line, the line
voiced the old way, and voiced the new way. An admin hears the original, then
A and B (old and new in an order of their own, fixed per person and trial, so
it is blind and stays put on reload), and votes. Only after voting does the
page say which was which, with the scores.

The runs live under AVE_VOICE_AB_DIR, by default `backend/evals/results/voice-ab`
(committed with the eval). Names come from the folder, never from the request,
so a path in a URL can only ever name a file the eval wrote.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from app.timefmt import now_iso

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "evals" / "results" / "voice-ab"
METHODS = ("old", "new")
CHOICES = ("a", "b", "same")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def root() -> Path:
    return Path(os.environ.get("AVE_VOICE_AB_DIR") or DEFAULT_DIR)


def runs() -> list[str]:
    """Runs with trials, newest first (folder names start with their UTC time)."""
    base = root()
    if not base.is_dir():
        return []
    return sorted((p.name for p in base.iterdir() if (p / "trials.json").is_file() and _NAME.match(p.name)),
                  reverse=True)


def load(run: str) -> dict | None:
    if run not in runs():
        return None
    try:
        return json.loads((root() / run / "trials.json").read_text())
    except (OSError, ValueError):
        return None


def _complete(t: dict) -> bool:
    """A trial the page can play: the original and both methods, with scores for both."""
    return {"original", *METHODS} <= set(t.get("files") or {}) and all((t.get("scores") or {}).get(m) for m in METHODS)


def trials(run: str) -> list[dict]:
    return [t for t in (load(run) or {}).get("trials", ()) if _complete(t)]


def trial(run: str, trial_id: str) -> dict | None:
    return next((t for t in trials(run) if t.get("id") == trial_id), None)


def first(run: str, trial_id: str, voter: str) -> str:
    """Which method this person hears as A: blind, but the same every time they look."""
    digest = hashlib.sha256(f"{run}|{trial_id}|{voter}".encode()).digest()
    return METHODS[digest[0] % 2]


def method_of(run: str, trial_id: str, voter: str, slot: str) -> str:
    a = first(run, trial_id, voter)
    return a if slot == "a" else METHODS[1 - METHODS.index(a)]


def clip_path(run: str, trial_id: str, voter: str, clip: str) -> Path | None:
    """The file behind `original`, `a` or `b` for this person, or None."""
    t = trial(run, trial_id)
    if t is None or clip not in ("original", "a", "b"):
        return None
    key = clip if clip == "original" else method_of(run, trial_id, voter, clip)
    name = (t.get("files") or {}).get(key)
    if not name or not _NAME.match(name):
        return None
    path = root() / run / name
    return path if path.is_file() else None


def vote(c, run: str, trial_id: str, voter: str, choice: str) -> str:
    """Record (or change) a vote; returns the method picked: old | new | same."""
    picked = "same" if choice == "same" else method_of(run, trial_id, voter, choice)
    c.execute("DELETE FROM voice_ab_votes WHERE run = ? AND trial = ? AND voter = ?", (run, trial_id, voter))
    c.execute("INSERT INTO voice_ab_votes (run, trial, voter, picked, heard_as_a, at) VALUES (?, ?, ?, ?, ?, ?)",
              (run, trial_id, voter, picked, first(run, trial_id, voter), now_iso()))
    return picked


def page(c, run: str, voter: str) -> dict:
    """The run as this person sees it: blind until they vote, then revealed."""
    data = load(run) or {}
    mine = {r[0]: r[1] for r in c.execute(
        "SELECT trial, picked FROM voice_ab_votes WHERE run = ? AND voter = ?", (run, voter)).fetchall()}
    tally = {"old": 0, "new": 0, "same": 0}
    voters = set()
    for picked, who in c.execute("SELECT picked, voter FROM voice_ab_votes WHERE run = ?", (run,)).fetchall():
        tally[picked] = tally.get(picked, 0) + 1
        voters.add(who)
    items = []
    for t in trials(run):
        tid = t.get("id")
        picked = mine.get(tid)
        a = first(run, tid, voter)
        item = {"id": tid, "speaker": t.get("speaker"), "before": t.get("before"), "after": t.get("after"),
                "start": t.get("start"), "end": t.get("end"), "voted": picked is not None}
        if picked is not None:
            item["choice"] = "same" if picked == "same" else ("a" if picked == a else "b")
            item["a_is"] = a
            item["scores"] = t.get("scores")
        items.append(item)
    return {"run": run, "runs": runs(), "clip": data.get("clip"), "made_at": data.get("made_at"),
            "summary": data.get("summary"), "trials": items, "tally": tally, "voters": len(voters)}
