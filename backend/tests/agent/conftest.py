"""Fakes for the agent tests: a scripted Claude client, a workbench over an
in-memory store, and a record for a silent 7.5 s clip."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.guards import TurnBudget
from app.agent.tools import Turn, Workbench
from app.domain.models import Selection, Transcript
from app.domain.plan import Plan
from app.store.db import Database
from app.store.repository import ProjectRepository
from app.usage import Ledger
from tests.factories import make_source

VOICES = [
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "description": "Mature, Reassuring", "gender": "female", "accent": "american", "age": None},
    {"voice_id": "kL06KYMvPY56NluIQ72m", "name": "Varsha", "description": "Warm and Clear", "gender": "female", "accent": "indian", "age": "middle_aged"},
]


class ScriptedClient:
    """Answers `create` with the next scripted response. Blocks are dicts."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.calls.append(params)
        if not self.responses:
            raise AssertionError("the script ran out of responses")
        return self.responses.pop(0)


def reply(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def text(t):
    return {"type": "text", "text": t}


def use(name, _id="tu1", **args):
    return {"type": "tool_use", "id": _id, "name": name, "input": args}


class FakeCandidate:
    def __init__(self, candidate_id, selection, new_text, passed=True, warnings=()):
        self.candidate_id = candidate_id
        self.plan = SimpleNamespace(selection=selection, new_text=new_text, fit=None, voice_profile_id="v", delivery=None,
                                    voice_settings=None, model=None)
        self.continuity = SimpleNamespace(passed=passed, warnings=tuple(warnings), prosody=None, audio_integration=None,
                                          voice_match=None, naturalness=None, measured=())
        self.fit_notes = ("nearest of 3 takes",)
        self.audio = SimpleNamespace(duration=1.0, sha256="b" * 64)
        self.words = (SimpleNamespace(text="Welcome", start=0.0, end=0.5), SimpleNamespace(text="to", start=0.5, end=0.6),
                      SimpleNamespace(text="Goa", start=0.6, end=1.0))


@pytest.fixture()
def world():
    db = Database(":memory:")
    repo = ProjectRepository(db)
    ledger = Ledger(db, ceiling_usd=2.0)
    repo.create(make_source(project_id="p1", filename="beach.mp4", duration=7.5), Transcript(words=()))
    record = repo.get("p1")
    plan = Plan(plan_id="plan1", project_id="p1", goal="", summary="", items=(), mode="draft", status="proposed",
                created_at="2026-10-17T00:00:00+00:00")
    repo.save_plan(plan)
    made: list[dict] = []
    shipped: list[list[str]] = []

    def generate(project_id, rec, candidate_id, selection, text_, voice_id, fit, mix, on_long, report, delivery=None, voice_notes=(),
                 voice_settings=None, model=None, flex_max=None, max_regenerations=None):
        made.append({"candidate_id": candidate_id, "selection": selection, "text": text_, "voice_id": voice_id, "mix": mix,
                     "delivery": delivery, "voice_settings": voice_settings, "model": model, "fit": fit, "flex_max": flex_max,
                     "voice_notes": tuple(voice_notes), "max_regenerations": max_regenerations})
        ledger.record(project_id, "elevenlabs", "take", len(text_), "characters", 0.03)
        report(0.5, "Synthesizing the new line")
        c = FakeCandidate(candidate_id, selection, text_)
        c.plan.voice_settings, c.plan.model, c.plan.delivery = voice_settings, model, delivery
        repo_candidates[candidate_id] = c
        return c

    repo_candidates: dict = {}
    designed: list[dict] = []
    saved: list[tuple] = []
    added: list[tuple] = []
    deleted: list[str] = []
    audio: list[tuple] = []

    def design(project_id, description, text):
        designed.append({"description": description, "text": text})
        ledger.record(project_id, "elevenlabs", "design", 350, "characters", 0.105)
        sample = text or "The vendor's own sample text, a little over one hundred characters long so that the previews show the voice."
        return [{"generated_voice_id": f"g{n}", "audio": b"mp3" + bytes([n]), "media_type": "audio/mpeg", "duration": 20.0 + n, "text": sample}
                for n in (1, 2, 3)]

    def save_voice(gid, name, description):
        saved.append((gid, name, description))
        return "NEWVOICE" + gid

    def add_from_library(owner, vid, name):
        added.append((owner, vid, name))
        return vid

    # 20c: a speech clip's lines and speakers, set by a test; the clone and the cuts as fakes.
    lines: list = []
    speakers: list = []
    cloned: list[tuple] = []
    removed: list[tuple] = []
    shifted: list[tuple] = []
    moved: list[tuple] = []

    def voice_for(project_id, rec, selection, requested, speaker):
        cloned.append((speaker, requested))
        spk = next((s for s in speakers if s.label == speaker), None)
        if spk is None:
            return SimpleNamespace(voice_id=requested, notes=(), cloned=False)
        if spk.name == "Mute":
            return SimpleNamespace(voice_id=requested, notes=("Stock voice: only 3.0 s of Mute's voice, 10 s needed to clone it.",), cloned=False)
        spk.clone_voice_id = "CLONE" + spk.label
        return SimpleNamespace(voice_id="CLONE" + spk.label, notes=(), cloned=True)

    def remove_words(project_id, rec, span):
        removed.append((span.start, span.end))
        return {"edit_id": "e-rm", "candidate_id": "c-rm", "selection": {"start": span.start, "end": span.end}, "mix": "remove"}

    def shift_words(project_id, rec, span, to):
        shifted.append((span.start, span.end, to))
        return {"edit_id": "e-sh", "removed_edit_id": "e-rm", "candidate": {}, "from": {"start": span.start, "end": span.end},
                "selection": {"start": to, "end": to + (span.end - span.start)}, "mix": "layer"}

    def move_take(project_id, rec, candidate, start, mix):
        moved.append((candidate.candidate_id, start))
        length = candidate.plan.selection.end - candidate.plan.selection.start
        c = FakeCandidate(candidate.candidate_id + "m", Selection(start, start + length), candidate.plan.new_text)
        repo_candidates[c.candidate_id] = c
        return c

    def put_audio(project_id, data, container, duration):
        audio.append((project_id, data, container, duration))
        return SimpleNamespace(sha256="a" * 63 + str(len(audio)), duration=duration)

    def ship(project_id, rec, plan_id, item_ids):
        shipped.append(list(item_ids))
        p = repo.get_plan(project_id, plan_id)
        for i in p.items:
            if i.item_id in item_ids:
                repo.update_item(project_id, plan_id, i.item_id, status="approved", edit_id=f"e-{i.item_id}")
        return {"approved": [{"item_id": i} for i in item_ids], "skipped": [], "export": {"render": {"sha256": "r" * 64}}}

    wb = Workbench(
        repo=repo, ledger=ledger,
        frames=lambda rec: [], lines=lambda rec: list(lines),
        room_after=lambda transcript, selection, duration: 0.0,
        voices=lambda: VOICES, library=lambda accent, language="en": [],
        estimate_usd=lambda t: (len(t), round(len(t) * 0.0003, 4)),
        generate=generate, ensure_spend=lambda project_id: None, ship=ship,
        default_voice=lambda: "EXAVITQu4vr4xnSDxMaL",
        hear=lambda rec, start, end: {"noise_db": -40.0, "speech_db": None},
        sight_text=lambda project_id: "A wide beach at sunset.",
        design=design, design_cost=lambda text=None: ((len(text) if text else 350), round((len(text) if text else 350) * 0.0003, 4)),
        save_voice=save_voice, add_from_library=add_from_library, delete_voice=deleted.append,
        slots=lambda: (3, 30), put_audio=put_audio,
        speakers=lambda project_id: list(speakers), voice_for=voice_for, remove_words=remove_words, shift_words=shift_words,
        move_take=move_take,
    )
    # The repo's candidate store is what `measure` reads; the fake pipeline fills it.
    repo.get_candidate = lambda project_id, candidate_id: repo_candidates.get(candidate_id)

    def turn(autonomy="draft", approved=False, budget=None, commit_approved=False):
        return Turn(project_id="p1", record=record, plan_id="plan1", autonomy=autonomy, spend_approved=approved,
                    budget=budget or TurnBudget(), started_at="2000-01-01T00:00:00+00:00", commit_approved=commit_approved)

    return SimpleNamespace(repo=repo, ledger=ledger, record=record, wb=wb, turn=turn, made=made, shipped=shipped,
                           designed=designed, saved=saved, added=added, deleted=deleted, audio=audio,
                           lines=lines, speakers=speakers, cloned=cloned, removed=removed, shifted=shifted, moved=moved)
