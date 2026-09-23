from app.domain.models import (
    Transcript, Word, Selection, EditPlan, ApprovedEdit,
    EditCandidate, ContinuityReport, MediaArtifact,
)
from app.store.repository import ProjectRepository
from tests.factories import make_source

TRANSCRIPT = Transcript(words=(Word("Get", 0.0, 0.4),))
PLAN = EditPlan(Selection(0.0, 0.4), "Grab", "speaker-1")
AUDIO = MediaArtifact("audio", "a" * 64, "/tmp/a.wav", 0.4, "wav")
FRAMES = MediaArtifact("video", "f" * 64, "/tmp/f.mp4", 0.4, "mp4")
PASSED = ContinuityReport(0.9, 0.9, 0.9, 0.9, True, ())


def make_edit(edit_id: str) -> ApprovedEdit:
    return ApprovedEdit(edit_id, f"c-{edit_id}", PLAN, AUDIO, FRAMES)


def make_candidate(candidate_id: str) -> EditCandidate:
    return EditCandidate(candidate_id, PLAN, AUDIO, FRAMES, PASSED)


def seeded_repo() -> tuple[ProjectRepository, str]:
    repo = ProjectRepository()
    pid = repo.next_id()
    repo.create(make_source(project_id=pid), TRANSCRIPT)
    return repo, pid


def test_ids_are_sequential():
    repo = ProjectRepository()
    assert repo.next_id() == "p1"
    assert repo.next_id() == "p2"


def test_create_get_and_append_edits():
    repo, pid = seeded_repo()

    record = repo.get(pid)
    assert record.source.filename == "ad.mp4"
    assert record.transcript == TRANSCRIPT
    assert repo.list_edits(pid) == []

    repo.append_edit(pid, make_edit("e1"))
    repo.append_edit(pid, make_edit("e2"))
    assert [e.edit_id for e in repo.list_edits(pid)] == ["e1", "e2"]


def test_get_unknown_project_returns_none():
    assert ProjectRepository().get("nope") is None


def test_candidate_ids_are_sequential_per_project():
    repo, pid = seeded_repo()
    other = repo.next_id()
    repo.create(make_source(project_id=other, filename="b.mp4", duration=5.0), TRANSCRIPT)

    assert repo.next_candidate_id(pid) == "c1"
    assert repo.next_candidate_id(pid) == "c2"
    # A second project numbers its own candidates from scratch.
    assert repo.next_candidate_id(other) == "c1"


def test_candidates_are_saved_and_retrievable():
    repo, pid = seeded_repo()
    candidate = make_candidate("c1")
    repo.save_candidate(pid, candidate)

    assert repo.get_candidate(pid, "c1") == candidate


def test_every_candidate_is_retained_not_overwritten():
    # Design spec §7: nothing is lost; rollback is always available.
    repo, pid = seeded_repo()
    repo.save_candidate(pid, make_candidate("c1"))
    repo.save_candidate(pid, make_candidate("c2"))

    assert repo.get_candidate(pid, "c1") is not None
    assert repo.get_candidate(pid, "c2") is not None


def test_unknown_candidate_returns_none():
    repo, pid = seeded_repo()
    assert repo.get_candidate(pid, "nope") is None
    assert repo.get_candidate("no-project", "c1") is None


def test_projects_start_without_consent():
    repo, pid = seeded_repo()
    assert repo.get(pid).consent is None


def test_consent_can_be_recorded_at_creation():
    from app.domain.models import Consent
    repo = ProjectRepository()
    pid = repo.next_id()
    repo.create(make_source(project_id=pid), TRANSCRIPT, Consent("2026-09-23T00:00:00Z"))
    assert repo.get(pid).consent.granted_at == "2026-09-23T00:00:00Z"


def test_consent_can_be_granted_afterwards():
    from app.domain.models import Consent
    repo, pid = seeded_repo()
    repo.grant_consent(pid, Consent("2026-09-23T01:00:00Z"))
    assert repo.get(pid).consent.granted_at == "2026-09-23T01:00:00Z"


def test_the_first_grant_wins():
    from app.domain.models import Consent
    repo, pid = seeded_repo()
    repo.grant_consent(pid, Consent("first"))
    returned = repo.grant_consent(pid, Consent("second"))
    assert returned.granted_at == "first"
    assert repo.get(pid).consent.granted_at == "first"


def test_granting_consent_for_an_unknown_project_returns_none():
    from app.domain.models import Consent
    assert ProjectRepository().grant_consent("nope", Consent("x")) is None


def test_reset_clears_projects_and_counters():
    repo, pid = seeded_repo()
    repo.save_candidate(pid, make_candidate("c1"))
    repo.reset()

    assert repo.get(pid) is None
    assert repo.next_id() == "p1"
