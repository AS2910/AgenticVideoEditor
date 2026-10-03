"""A plan: what the agent proposes to change across the whole video (Phase 13).

A plan is made from a goal in the user's words. Each item is one line of the
transcript and the new words for it; the agent may also *suggest* changes the
goal implies but did not name, which join the plan only when the user adds
them. Items move planned → working → ready / needs-you / failed → approved as
the plan job runs and the user decides.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.domain.models import Selection

# Where an item stands.
ITEM_STATUSES = ("planned", "working", "ready", "needs-you", "failed", "approved",
                 "suggested", "dismissed")


@dataclass(frozen=True)
class PlanItem:
    item_id: str
    selection: Selection      # the line's span in the source
    old_text: str             # the line as spoken
    new_text: str             # the words to say instead
    speaker: str | None = None
    mix: str = "replace"      # "replace" | "concatenate" (added after the line)
    reason: str = ""          # why, in a few words
    kind: str = "planned"     # "planned" | "suggestion"
    enabled: bool = True      # ticked: part of the run
    status: str = "planned"
    fit: str | None = None    # how to place it once the user has answered
    candidate_id: str | None = None
    edit_id: str | None = None
    question: dict | None = None   # the open question, the agent's own fix first
    error: str | None = None
    note: str | None = None        # e.g. "The shorter line you picked"
    progress: str | None = None    # what is happening to it right now, in words


@dataclass(frozen=True)
class Plan:
    plan_id: str
    project_id: str
    goal: str
    summary: str
    items: tuple[PlanItem, ...]
    mode: str = "ask"              # "ask" (waits for Run) | "draft" (runs at once)
    status: str = "proposed"       # "proposed" | "running" | "done"
    created_at: str = ""
    log: tuple[dict, ...] = ()     # what Voltage did: {at, text, detail}
    estimate: dict = field(default_factory=dict)   # voice_characters, usd, seconds
    findings: tuple[str, ...] = ()  # what the planner noticed while reading
    # One thing the planner wants to know first: {text, options, guess}. The
    # plan's status is "clarifying" until it is answered (or the guess taken).
    question: dict | None = None

    def item(self, item_id: str) -> PlanItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)

    def with_item(self, item_id: str, **changes) -> "Plan":
        items = tuple(replace(i, **changes) if i.item_id == item_id else i for i in self.items)
        return replace(self, items=items)

    @property
    def runnable(self) -> tuple[PlanItem, ...]:
        """The ticked, planned items — what Run voices."""
        return tuple(i for i in self.items if i.kind == "planned" and i.enabled)


def item_from_dict(d: dict) -> PlanItem:
    return PlanItem(
        item_id=d["item_id"], selection=Selection(**d["selection"]), old_text=d["old_text"],
        new_text=d["new_text"], speaker=d.get("speaker"), mix=d.get("mix", "replace"),
        reason=d.get("reason", ""), kind=d.get("kind", "planned"), enabled=d.get("enabled", True),
        status=d.get("status", "planned"), fit=d.get("fit"), candidate_id=d.get("candidate_id"),
        edit_id=d.get("edit_id"), question=d.get("question"), error=d.get("error"), note=d.get("note"),
        progress=d.get("progress"),
    )


def plan_from_dict(d: dict) -> Plan:
    return Plan(
        plan_id=d["plan_id"], project_id=d["project_id"], goal=d["goal"], summary=d["summary"],
        items=tuple(item_from_dict(i) for i in d["items"]), mode=d.get("mode", "ask"),
        status=d.get("status", "proposed"), created_at=d.get("created_at", ""),
        log=tuple(d.get("log", ())), estimate=d.get("estimate", {}),
        findings=tuple(d.get("findings", ())), question=d.get("question"),
    )
