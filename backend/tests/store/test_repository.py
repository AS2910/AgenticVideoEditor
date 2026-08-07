from app.domain.models import Source, Transcript, Word, Selection, EditPlan, ApprovedEdit
from app.store.repository import ProjectRepository

TRANSCRIPT = Transcript(words=(Word("Get", 0.0, 0.4),))


def make_edit(edit_id: str) -> ApprovedEdit:
    plan = EditPlan(Selection(0.0, 0.4), "Grab", "speaker-1")
    return ApprovedEdit(edit_id=edit_id, plan=plan, audio_ref="audio://x", frames_ref="frames://x")


def test_ids_are_sequential():
    repo = ProjectRepository()
    assert repo.next_id() == "p1"
    assert repo.next_id() == "p2"


def test_create_get_and_append_edits():
    repo = ProjectRepository()
    pid = repo.next_id()
    source = Source(project_id=pid, filename="ad.mp4", duration=30.0)
    repo.create(source, TRANSCRIPT)

    record = repo.get(pid)
    assert record.source.filename == "ad.mp4"
    assert record.transcript == TRANSCRIPT
    assert repo.list_edits(pid) == []

    repo.append_edit(pid, make_edit("e1"))
    repo.append_edit(pid, make_edit("e2"))
    assert [e.edit_id for e in repo.list_edits(pid)] == ["e1", "e2"]


def test_get_unknown_project_returns_none():
    assert ProjectRepository().get("nope") is None
