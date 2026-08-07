from dataclasses import dataclass, field
from app.domain.models import Source, Transcript, ApprovedEdit


@dataclass
class ProjectRecord:
    source: Source                       # immutable original
    transcript: Transcript
    edits: list[ApprovedEdit] = field(default_factory=list)


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

    def create(self, source: Source, transcript: Transcript) -> None:
        self._projects[source.project_id] = ProjectRecord(source=source, transcript=transcript)

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._projects.get(project_id)

    def append_edit(self, project_id: str, edit: ApprovedEdit) -> None:
        self._projects[project_id].edits.append(edit)

    def list_edits(self, project_id: str) -> list[ApprovedEdit]:
        record = self._projects.get(project_id)
        if record is None:
            return []
        return list(record.edits)
