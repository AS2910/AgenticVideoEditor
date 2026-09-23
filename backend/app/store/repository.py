from dataclasses import dataclass, field

from app.domain.models import Source, Transcript, ApprovedEdit, EditCandidate, Consent


@dataclass
class ProjectRecord:
    source: Source                       # immutable original
    transcript: Transcript
    # None until the uploader confirms rights. Generation is refused without it.
    consent: Consent | None = None
    # Every candidate ever previewed is retained (design spec §7: nothing is
    # lost, rollback is always available) and is what approval commits.
    candidates: dict[str, EditCandidate] = field(default_factory=dict)
    edits: list[ApprovedEdit] = field(default_factory=list)
    candidate_counter: int = 0


class ProjectRepository:
    """In-memory store. Source is never mutated; edits only ever append."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectRecord] = {}
        self._counter = 0

    def reset(self) -> None:
        """Clear all projects and id counter. Intended for test isolation."""
        self._projects.clear()
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"p{self._counter}"

    def create(
        self, source: Source, transcript: Transcript, consent: Consent | None = None,
    ) -> None:
        self._projects[source.project_id] = ProjectRecord(
            source=source, transcript=transcript, consent=consent,
        )

    def grant_consent(self, project_id: str, consent: Consent) -> Consent | None:
        """Record consent for a project that was uploaded without it."""
        record = self._projects.get(project_id)
        if record is None:
            return None
        # First grant wins, so re-confirming cannot quietly restamp the record.
        if record.consent is None:
            record.consent = consent
        return record.consent

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._projects.get(project_id)

    def next_candidate_id(self, project_id: str) -> str:
        record = self._projects[project_id]
        record.candidate_counter += 1
        return f"c{record.candidate_counter}"

    def save_candidate(self, project_id: str, candidate: EditCandidate) -> None:
        self._projects[project_id].candidates[candidate.candidate_id] = candidate

    def get_candidate(self, project_id: str, candidate_id: str) -> EditCandidate | None:
        record = self._projects.get(project_id)
        if record is None:
            return None
        return record.candidates.get(candidate_id)

    def append_edit(self, project_id: str, edit: ApprovedEdit) -> None:
        self._projects[project_id].edits.append(edit)

    def list_edits(self, project_id: str) -> list[ApprovedEdit]:
        record = self._projects.get(project_id)
        if record is None:
            return []
        return list(record.edits)
