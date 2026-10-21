"""G1: the sample project.

A new owner's Home starts with one project, "Sample: bhaji-cam ad", holding
the bundled sample ad as a tutorial video (its turns replay the recorded run
in `fixture/script.json`; nothing is voiced or spent). It is made once per
owner, the first time Home loads or they sign in, and only for an owner with
nothing yet: someone with work of their own does not get a folder they did
not ask for. The record (`sample:<owner>` in meta) stays after the project
is deleted, so it never comes back on its own.
"""
from __future__ import annotations

import json

from app import analytics

from app.tutorial import start as start_tutorial

NAME = "Sample: bhaji-cam ad"
BRIEF = ("A 20 second ad for Bhaji Cam, a pocket camera for street food videos. Bright and quick. "
         "The offer is 30% off this week. Say the brand as one word.")


def _api():
    from app.api import main
    return main


def key(owner: str) -> str:
    return f"sample:{owner}"


def record(owner: str) -> dict | None:
    raw = _api().repo.get_meta(key(owner))
    return json.loads(raw) if raw else None


def sample_project_id(owner: str) -> str | None:
    found = record(owner)
    return found.get("project_id") if found else None


def ensure(owner: str) -> dict:
    """Make the sample project when this owner has never had one and has
    nothing yet. Returns {"created": bool, "project_id": id or None}."""
    api = _api()
    repo = api.repo
    if not api.flags.enabled("golive.g1", owner):
        return {"created": False, "project_id": None}
    with api._samples_lock:
        found = record(owner)
        if found is not None:
            return {"created": False, "project_id": found.get("project_id")}
        if repo.list_projects(owner, include_deleted=True) or repo.list(owner, include_deleted=True):
            repo.set_meta(key(owner), json.dumps({"project_id": None, "at": api._now(), "skipped": "had work"}))
            analytics.track("sample.skipped", owner, {"why": "had work"})
            return {"created": False, "project_id": None}
        project = repo.create_project(owner, NAME, BRIEF)
        video = start_tutorial(owner)
        repo.set_folder(video["video_id"], project.project_id)
        repo.set_meta(key(owner), json.dumps({"project_id": project.project_id, "video_id": video["video_id"],
                                             "at": api._now()}))
    analytics.track("sample.created", owner, {"project_id": project.project_id})
    return {"created": True, "project_id": project.project_id}
