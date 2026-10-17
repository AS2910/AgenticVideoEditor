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
        self.plan = SimpleNamespace(selection=selection, new_text=new_text, fit=None, voice_profile_id="v")
        self.continuity = SimpleNamespace(passed=passed, warnings=tuple(warnings))
        self.fit_notes = ("nearest of 3 takes",)
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

    def generate(project_id, rec, candidate_id, selection, text_, voice_id, fit, mix, on_long, report, delivery=None, voice_notes=()):
        made.append({"candidate_id": candidate_id, "selection": selection, "text": text_, "voice_id": voice_id, "mix": mix, "delivery": delivery})
        ledger.record(project_id, "elevenlabs", "take", len(text_), "characters", 0.03)
        report(0.5, "Synthesizing the new line")
        return FakeCandidate(candidate_id, selection, text_)

    def ship(project_id, rec, plan_id, item_ids):
        shipped.append(list(item_ids))
        p = repo.get_plan(project_id, plan_id)
        for i in p.items:
            if i.item_id in item_ids:
                repo.update_item(project_id, plan_id, i.item_id, status="approved", edit_id=f"e-{i.item_id}")
        return {"approved": [{"item_id": i} for i in item_ids], "skipped": [], "export": {"render": {"sha256": "r" * 64}}}

    wb = Workbench(
        repo=repo, ledger=ledger,
        frames=lambda rec: [], lines=lambda rec: [],
        room_after=lambda transcript, selection, duration: 0.0,
        voices=lambda: VOICES, library=lambda accent, language="en": [],
        estimate_usd=lambda t: (len(t), round(len(t) * 0.0003, 4)),
        generate=generate, ensure_spend=lambda project_id: None, ship=ship,
        default_voice=lambda: "EXAVITQu4vr4xnSDxMaL",
        hear=lambda rec, start, end: {"noise_db": -40.0, "speech_db": None},
        sight_text=lambda project_id: "A wide beach at sunset.",
    )

    def turn(autonomy="draft", approved=False, budget=None, commit_approved=False):
        return Turn(project_id="p1", record=record, plan_id="plan1", autonomy=autonomy, spend_approved=approved,
                    budget=budget or TurnBudget(), started_at="2000-01-01T00:00:00+00:00", commit_approved=commit_approved)

    return SimpleNamespace(repo=repo, ledger=ledger, record=record, wb=wb, turn=turn, made=made, shipped=shipped)
