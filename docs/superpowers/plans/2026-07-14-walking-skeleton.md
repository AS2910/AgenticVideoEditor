# Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin-but-real end-to-end backend for the Agentic Video Editor: ingest a video's metadata, transcribe it, preview a dialogue edit through the full pipeline (plan → generate → continuity check), approve it onto a non-destructive edit stack, and export a render manifest — all driven over HTTP with mock generation adapters.

**Architecture:** Python FastAPI backend with four cleanly separated layers from the spec — a domain core (immutable source + non-destructive edit stack), swappable generation adapters (mock implementations for now), a continuity engine, and an agent orchestrator (planner + pipeline) — plus an in-memory repository and a render step. Generation vendors are hidden behind adapter interfaces so they can be swapped later without touching the rest of the system. The React "Voltage" front-end is a separate follow-on plan that wires to these endpoints.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pytest, httpx (via FastAPI `TestClient`). No real video/AI processing in this slice — adapters are deterministic mocks so the whole suite runs offline.

---

## Scope of this plan

**In:** the backend edit lifecycle end-to-end via HTTP, fully TDD'd against mocks.

**Out (later plans):** React front-end, real transcription/voice/lip-sync vendors, real ffmpeg rendering, persistence beyond in-memory, auth, the consent-gate UI. These plug into the interfaces built here.

## File Structure

All backend code lives under `backend/`. Each file has one responsibility.

- `backend/pyproject.toml` — project + pytest config, dependencies
- `backend/app/__init__.py` — package marker
- `backend/app/domain/models.py` — frozen dataclasses: `Word`, `Transcript`, `Source`, `Selection`, `EditPlan`, `ContinuityReport`, `EditCandidate`, `ApprovedEdit`
- `backend/app/domain/transcript.py` — `snap_to_word_boundaries()`
- `backend/app/adapters/base.py` — `TranscriptionAdapter`, `VoiceAdapter`, `LipSyncAdapter` protocols
- `backend/app/adapters/mock.py` — deterministic mock adapters
- `backend/app/continuity/engine.py` — `ContinuityEngine` + thresholds
- `backend/app/orchestrator/planner.py` — `extract_new_text()`, `build_edit_plan()`
- `backend/app/orchestrator/pipeline.py` — `run_edit()`
- `backend/app/store/repository.py` — `ProjectRecord`, `ProjectRepository`
- `backend/app/render/renderer.py` — `RenderSegment`, `RenderManifest`, `render()`
- `backend/app/api/main.py` — FastAPI app + endpoints
- `backend/tests/...` — one test module per component

Every non-test directory under `backend/app/` also gets an empty `__init__.py`.

---

### Task 0: Project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/tests/__init__.py` (empty)
- Test: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_smoke.py`:
```python
def test_app_package_importable():
    import app
    assert app is not None
```

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "agentic-video-editor-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "pydantic>=2.6",
    "uvicorn>=0.29",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 3: Create empty package markers**

Create `backend/app/__init__.py` and `backend/tests/__init__.py`, both empty.

- [ ] **Step 4: Install deps and run the test**

Run:
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m pytest tests/test_smoke.py -v
```
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/tests/__init__.py backend/tests/test_smoke.py
git commit -m "chore: scaffold FastAPI backend package"
```

---

### Task 1: Domain models

**Files:**
- Create: `backend/app/domain/__init__.py` (empty)
- Create: `backend/app/domain/models.py`
- Test: `backend/tests/domain/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/__init__.py` (empty) and `backend/tests/domain/test_models.py`:
```python
from app.domain.models import (
    Word, Transcript, Source, Selection, EditPlan,
    ContinuityReport, EditCandidate, ApprovedEdit,
)


def test_models_construct_and_are_frozen():
    word = Word(text="hello", start=0.0, end=0.5)
    transcript = Transcript(words=(word,))
    source = Source(project_id="p1", filename="ad.mp4", duration=30.0)
    selection = Selection(start=0.0, end=0.5)
    plan = EditPlan(selection=selection, new_text="hi", voice_profile_id="speaker-1")
    report = ContinuityReport(
        voice_match=0.9, prosody=0.9, audio_integration=0.9,
        lip_sync=0.9, passed=True, warnings=(),
    )
    candidate = EditCandidate(
        plan=plan, audio_ref="audio://x", frames_ref="frames://x", continuity=report,
    )
    approved = ApprovedEdit(
        edit_id="e1", plan=plan, audio_ref="audio://x", frames_ref="frames://x",
    )

    assert transcript.words[0].text == "hello"
    assert candidate.continuity.passed is True
    assert approved.edit_id == "e1"

    import dataclasses
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.duration = 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/domain/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain'`.

- [ ] **Step 3: Write the implementation**

`backend/app/domain/models.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds
    end: float    # seconds


@dataclass(frozen=True)
class Transcript:
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Source:
    project_id: str
    filename: str
    duration: float  # seconds


@dataclass(frozen=True)
class Selection:
    start: float
    end: float


@dataclass(frozen=True)
class EditPlan:
    selection: Selection
    new_text: str
    voice_profile_id: str


@dataclass(frozen=True)
class ContinuityReport:
    voice_match: float
    prosody: float
    audio_integration: float
    lip_sync: float
    passed: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class EditCandidate:
    plan: EditPlan
    audio_ref: str
    frames_ref: str
    continuity: ContinuityReport


@dataclass(frozen=True)
class ApprovedEdit:
    edit_id: str
    plan: EditPlan
    audio_ref: str
    frames_ref: str
```

Also create empty `backend/app/domain/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/domain/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain backend/tests/domain
git commit -m "feat: add domain models"
```

---

### Task 2: Transcript boundary snapping

**Files:**
- Create: `backend/app/domain/transcript.py`
- Test: `backend/tests/domain/test_transcript.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/domain/test_transcript.py`:
```python
from app.domain.models import Word, Transcript, Selection
from app.domain.transcript import snap_to_word_boundaries

TRANSCRIPT = Transcript(words=(
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
))


def test_snaps_outward_to_cover_selection():
    # selection lands mid-word on both ends
    snapped = snap_to_word_boundaries(TRANSCRIPT, Selection(0.5, 1.0))
    assert snapped == Selection(0.4, 1.3)  # start of "20%" to end of "off"


def test_selection_on_exact_boundaries_is_unchanged():
    snapped = snap_to_word_boundaries(TRANSCRIPT, Selection(0.4, 1.3))
    assert snapped == Selection(0.4, 1.3)


def test_empty_transcript_returns_selection_unchanged():
    snapped = snap_to_word_boundaries(Transcript(words=()), Selection(0.5, 1.0))
    assert snapped == Selection(0.5, 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/domain/test_transcript.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.transcript'`.

- [ ] **Step 3: Write the implementation**

`backend/app/domain/transcript.py`:
```python
from app.domain.models import Transcript, Selection


def snap_to_word_boundaries(transcript: Transcript, selection: Selection) -> Selection:
    """Widen a selection outward to the nearest enclosing word boundaries.

    Ensures cuts land in natural silences between words rather than mid-syllable.
    """
    words = transcript.words
    if not words:
        return selection

    starts_at_or_before = [w.start for w in words if w.start <= selection.start]
    new_start = max(starts_at_or_before) if starts_at_or_before else words[0].start

    ends_at_or_after = [w.end for w in words if w.end >= selection.end]
    new_end = min(ends_at_or_after) if ends_at_or_after else words[-1].end

    return Selection(start=new_start, end=new_end)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/domain/test_transcript.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/transcript.py backend/tests/domain/test_transcript.py
git commit -m "feat: snap selection to word boundaries"
```

---

### Task 3: Adapter interfaces and mocks

**Files:**
- Create: `backend/app/adapters/__init__.py` (empty)
- Create: `backend/app/adapters/base.py`
- Create: `backend/app/adapters/mock.py`
- Test: `backend/tests/adapters/test_mock.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/adapters/__init__.py` (empty) and `backend/tests/adapters/test_mock.py`:
```python
from app.domain.models import Source, Selection, EditPlan
from app.adapters.mock import (
    MockTranscriptionAdapter, MockVoiceAdapter, MockLipSyncAdapter,
)

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=30.0)
PLAN = EditPlan(selection=Selection(0.4, 1.3), new_text="30% off", voice_profile_id="speaker-1")


def test_transcription_returns_words_with_timestamps():
    transcript = MockTranscriptionAdapter().transcribe(SOURCE)
    assert len(transcript.words) > 0
    assert transcript.words[0].start == 0.0
    # timestamps are monotonic
    for earlier, later in zip(transcript.words, transcript.words[1:]):
        assert earlier.end <= later.start


def test_voice_synthesis_is_deterministic_and_text_sensitive():
    voice = MockVoiceAdapter()
    a = voice.synthesize("30% off", "speaker-1")
    b = voice.synthesize("30% off", "speaker-1")
    c = voice.synthesize("40% off", "speaker-1")
    assert a == b            # deterministic
    assert a != c            # different text -> different ref
    assert a.startswith("audio://")


def test_lipsync_returns_frames_ref():
    frames = MockLipSyncAdapter().sync(SOURCE, PLAN, "audio://xyz")
    assert frames.startswith("frames://")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/adapters/test_mock.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters'`.

- [ ] **Step 3: Write the interfaces**

`backend/app/adapters/base.py`:
```python
from typing import Protocol
from app.domain.models import Source, Transcript, EditPlan


class TranscriptionAdapter(Protocol):
    def transcribe(self, source: Source) -> Transcript: ...


class VoiceAdapter(Protocol):
    def synthesize(self, text: str, voice_profile_id: str) -> str:
        """Return an opaque reference to generated audio."""
        ...


class LipSyncAdapter(Protocol):
    def sync(self, source: Source, plan: EditPlan, audio_ref: str) -> str:
        """Return an opaque reference to the re-synced frames."""
        ...
```

- [ ] **Step 4: Write the mocks**

`backend/app/adapters/mock.py`:
```python
import hashlib
from app.domain.models import Source, Transcript, Word, EditPlan

# A fixed canned transcript so the whole pipeline is deterministic offline.
_CANNED_WORDS = (
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
    Word("only", 1.8, 2.3),
)


def _digest(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


class MockTranscriptionAdapter:
    def transcribe(self, source: Source) -> Transcript:
        return Transcript(words=_CANNED_WORDS)


class MockVoiceAdapter:
    def synthesize(self, text: str, voice_profile_id: str) -> str:
        return f"audio://{voice_profile_id}/{_digest(voice_profile_id, text)}"


class MockLipSyncAdapter:
    def sync(self, source: Source, plan: EditPlan, audio_ref: str) -> str:
        ref = _digest(source.project_id, plan.new_text, audio_ref)
        return f"frames://{source.project_id}/{ref}"
```

Also create empty `backend/app/adapters/__init__.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/adapters/test_mock.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/adapters backend/tests/adapters
git commit -m "feat: add generation adapter interfaces and mocks"
```

---

### Task 4: Continuity engine

**Files:**
- Create: `backend/app/continuity/__init__.py` (empty)
- Create: `backend/app/continuity/engine.py`
- Test: `backend/tests/continuity/test_engine.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/continuity/__init__.py` (empty) and `backend/tests/continuity/test_engine.py`:
```python
from app.domain.models import Selection, EditPlan
from app.continuity.engine import ContinuityEngine

GOOD_PLAN = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
BAD_PLAN = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")


def test_known_voice_passes_continuity():
    report = ContinuityEngine().evaluate(GOOD_PLAN, "audio://x", "frames://x")
    assert report.passed is True
    assert report.warnings == ()
    assert report.voice_match >= 0.8


def test_unknown_voice_fails_with_warning():
    report = ContinuityEngine().evaluate(BAD_PLAN, "audio://x", "frames://x")
    assert report.passed is False
    assert any("voice" in w.lower() for w in report.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/continuity/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.continuity'`.

- [ ] **Step 3: Write the implementation**

`backend/app/continuity/engine.py`:
```python
from dataclasses import dataclass
from app.domain.models import EditPlan, ContinuityReport

# Metric keys, in a fixed order, paired with a human label for warnings.
_METRICS = (
    ("voice_match", "voice identity"),
    ("prosody", "prosody & energy"),
    ("audio_integration", "audio integration"),
    ("lip_sync", "lip-sync accuracy"),
)


@dataclass(frozen=True)
class ContinuityThresholds:
    voice_match: float = 0.8
    prosody: float = 0.8
    audio_integration: float = 0.8
    lip_sync: float = 0.8


def _mock_probe(plan: EditPlan) -> dict[str, float]:
    """Deterministic stand-in for real signal extraction.

    Replaced later by real audio/lip-sync analysis. For now a known voice
    profile scores high; an unknown one fails voice identity so the failure
    path is exercised end-to-end.
    """
    metrics = {
        "voice_match": 0.95,
        "prosody": 0.92,
        "audio_integration": 0.97,
        "lip_sync": 0.94,
    }
    if plan.voice_profile_id == "unknown":
        metrics["voice_match"] = 0.40
    return metrics


class ContinuityEngine:
    def __init__(self, thresholds: ContinuityThresholds | None = None) -> None:
        self.thresholds = thresholds or ContinuityThresholds()

    def evaluate(self, plan: EditPlan, audio_ref: str, frames_ref: str) -> ContinuityReport:
        metrics = _mock_probe(plan)
        warnings: list[str] = []
        for key, label in _METRICS:
            if metrics[key] < getattr(self.thresholds, key):
                warnings.append(f"Low {label} ({metrics[key]:.2f})")
        return ContinuityReport(
            voice_match=metrics["voice_match"],
            prosody=metrics["prosody"],
            audio_integration=metrics["audio_integration"],
            lip_sync=metrics["lip_sync"],
            passed=len(warnings) == 0,
            warnings=tuple(warnings),
        )
```

Also create empty `backend/app/continuity/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/continuity/test_engine.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/continuity backend/tests/continuity
git commit -m "feat: add continuity engine with thresholds"
```

---

### Task 5: Edit planner

**Files:**
- Create: `backend/app/orchestrator/__init__.py` (empty)
- Create: `backend/app/orchestrator/planner.py`
- Test: `backend/tests/orchestrator/test_planner.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/orchestrator/__init__.py` (empty) and `backend/tests/orchestrator/test_planner.py`:
```python
from app.domain.models import Selection
from app.orchestrator.planner import extract_new_text, build_edit_plan


def test_extract_new_text_from_change_to_pattern():
    assert extract_new_text('change "20% off" to "30% off"') == "30% off"


def test_extract_new_text_falls_back_to_whole_prompt():
    assert extract_new_text("make her say hello there") == "make her say hello there"


def test_build_edit_plan_uses_selection_and_voice():
    plan = build_edit_plan(
        prompt='change "20% off" to "30% off"',
        selection=Selection(0.4, 1.3),
        voice_profile_id="speaker-1",
    )
    assert plan.new_text == "30% off"
    assert plan.selection == Selection(0.4, 1.3)
    assert plan.voice_profile_id == "speaker-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/orchestrator/test_planner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.orchestrator'`.

- [ ] **Step 3: Write the implementation**

`backend/app/orchestrator/planner.py`:
```python
import re
from app.domain.models import Selection, EditPlan

# Matches the trailing '... to "NEW TEXT"' part of a change instruction.
_REPLACEMENT_RE = re.compile(r'to\s+"([^"]+)"\s*$', re.IGNORECASE)


def extract_new_text(prompt: str) -> str:
    """Pull the intended new spoken text out of a natural-language prompt.

    Recognises the common 'change "X" to "Y"' shape; otherwise treats the whole
    prompt as the literal new text. Real intent parsing replaces this later.
    """
    match = _REPLACEMENT_RE.search(prompt.strip())
    if match:
        return match.group(1)
    return prompt.strip()


def build_edit_plan(prompt: str, selection: Selection, voice_profile_id: str) -> EditPlan:
    return EditPlan(
        selection=selection,
        new_text=extract_new_text(prompt),
        voice_profile_id=voice_profile_id,
    )
```

Also create empty `backend/app/orchestrator/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/orchestrator/test_planner.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/orchestrator/__init__.py backend/app/orchestrator/planner.py backend/tests/orchestrator
git commit -m "feat: add edit planner"
```

---

### Task 6: Edit pipeline

**Files:**
- Create: `backend/app/orchestrator/pipeline.py`
- Test: `backend/tests/orchestrator/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/orchestrator/test_pipeline.py`:
```python
from app.domain.models import Source, Selection, EditPlan
from app.adapters.mock import MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.pipeline import run_edit

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=30.0)


def test_run_edit_produces_candidate_with_refs_and_report():
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run_edit(
        plan, SOURCE, MockVoiceAdapter(), MockLipSyncAdapter(), ContinuityEngine(),
    )
    assert candidate.plan == plan
    assert candidate.audio_ref.startswith("audio://")
    assert candidate.frames_ref.startswith("frames://")
    assert candidate.continuity.passed is True


def test_run_edit_surfaces_failed_continuity():
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")
    candidate = run_edit(
        plan, SOURCE, MockVoiceAdapter(), MockLipSyncAdapter(), ContinuityEngine(),
    )
    assert candidate.continuity.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/orchestrator/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.orchestrator.pipeline'`.

- [ ] **Step 3: Write the implementation**

`backend/app/orchestrator/pipeline.py`:
```python
from app.domain.models import Source, EditPlan, EditCandidate
from app.adapters.base import VoiceAdapter, LipSyncAdapter
from app.continuity.engine import ContinuityEngine


def run_edit(
    plan: EditPlan,
    source: Source,
    voice: VoiceAdapter,
    lipsync: LipSyncAdapter,
    continuity: ContinuityEngine,
) -> EditCandidate:
    """Run one dialogue edit through generation + continuity checking."""
    audio_ref = voice.synthesize(plan.new_text, plan.voice_profile_id)
    frames_ref = lipsync.sync(source, plan, audio_ref)
    report = continuity.evaluate(plan, audio_ref, frames_ref)
    return EditCandidate(
        plan=plan, audio_ref=audio_ref, frames_ref=frames_ref, continuity=report,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/orchestrator/test_pipeline.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/orchestrator/pipeline.py backend/tests/orchestrator/test_pipeline.py
git commit -m "feat: add edit pipeline"
```

---

### Task 7: Project repository (non-destructive store)

**Files:**
- Create: `backend/app/store/__init__.py` (empty)
- Create: `backend/app/store/repository.py`
- Test: `backend/tests/store/test_repository.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/store/__init__.py` (empty) and `backend/tests/store/test_repository.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/store/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.store'`.

- [ ] **Step 3: Write the implementation**

`backend/app/store/repository.py`:
```python
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
        return list(self._projects[project_id].edits)
```

Also create empty `backend/app/store/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/store/test_repository.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/store backend/tests/store
git commit -m "feat: add in-memory project repository"
```

---

### Task 8: Renderer (compose source + edit stack)

**Files:**
- Create: `backend/app/render/__init__.py` (empty)
- Create: `backend/app/render/renderer.py`
- Test: `backend/tests/render/test_renderer.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/render/__init__.py` (empty) and `backend/tests/render/test_renderer.py`:
```python
from app.domain.models import Source, Selection, EditPlan, ApprovedEdit
from app.render.renderer import render, RenderSegment

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=3.0)


def edit(edit_id, start, end):
    plan = EditPlan(Selection(start, end), "x", "speaker-1")
    return ApprovedEdit(edit_id, plan, "audio://x", f"frames://{edit_id}")


def test_no_edits_yields_single_original_segment():
    manifest = render(SOURCE, [])
    assert manifest.segments == (
        RenderSegment(0.0, 3.0, "original", "ad.mp4"),
    )


def test_edit_replaces_its_span_and_originals_fill_gaps():
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0)])
    assert manifest.segments == (
        RenderSegment(0.0, 1.0, "original", "ad.mp4"),
        RenderSegment(1.0, 2.0, "edited", "frames://e1"),
        RenderSegment(2.0, 3.0, "original", "ad.mp4"),
    )


def test_edits_are_ordered_by_start_time():
    manifest = render(SOURCE, [edit("e2", 2.0, 2.5), edit("e1", 0.5, 1.0)])
    kinds = [(s.kind, s.ref) for s in manifest.segments]
    assert kinds == [
        ("original", "ad.mp4"),
        ("edited", "frames://e1"),
        ("original", "ad.mp4"),
        ("edited", "frames://e2"),
        ("original", "ad.mp4"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/render/test_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.render'`.

- [ ] **Step 3: Write the implementation**

`backend/app/render/renderer.py`:
```python
from dataclasses import dataclass
from app.domain.models import Source, ApprovedEdit


@dataclass(frozen=True)
class RenderSegment:
    start: float
    end: float
    kind: str   # "original" | "edited"
    ref: str    # source filename for originals, frames_ref for edited spans


@dataclass(frozen=True)
class RenderManifest:
    segments: tuple[RenderSegment, ...]


def render(source: Source, edits: list[ApprovedEdit]) -> RenderManifest:
    """Composite the immutable source with approved edits into a segment list.

    Edited spans replace their region; original footage fills every gap.
    Real ffmpeg compositing replaces this in a later plan.
    """
    ordered = sorted(edits, key=lambda e: e.plan.selection.start)
    segments: list[RenderSegment] = []
    cursor = 0.0
    for e in ordered:
        sel = e.plan.selection
        if sel.start > cursor:
            segments.append(RenderSegment(cursor, sel.start, "original", source.filename))
        segments.append(RenderSegment(sel.start, sel.end, "edited", e.frames_ref))
        cursor = sel.end
    if cursor < source.duration:
        segments.append(RenderSegment(cursor, source.duration, "original", source.filename))
    return RenderManifest(segments=tuple(segments))
```

Also create empty `backend/app/render/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/render/test_renderer.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/render backend/tests/render
git commit -m "feat: add renderer that composites edits over source"
```

---

### Task 9: HTTP API

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/main.py`
- Test: `backend/tests/api/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/__init__.py` (empty) and `backend/tests/api/test_endpoints.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.api.main import app, repo


@pytest.fixture(autouse=True)
def reset_repo():
    repo._projects.clear()
    repo._counter = 0
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def create_project(client):
    resp = client.post("/projects", json={"filename": "ad.mp4", "duration": 30.0})
    assert resp.status_code == 200
    return resp.json()


def test_create_project_returns_id_and_transcript(client):
    body = create_project(client)
    assert body["project_id"] == "p1"
    assert body["transcript"][0]["text"] == "Get"


def test_preview_returns_candidate_with_continuity(client):
    create_project(client)
    resp = client.post("/projects/p1/edits/preview", json={
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"]["new_text"] == "30% off"
    assert body["plan"]["selection"] == {"start": 0.4, "end": 1.3}  # snapped
    assert body["continuity"]["passed"] is True


def test_preview_unknown_project_is_404(client):
    resp = client.post("/projects/nope/edits/preview", json={
        "prompt": "hi", "start": 0.0, "end": 1.0, "voice_profile_id": "speaker-1",
    })
    assert resp.status_code == 404


def test_approve_appends_edit_and_export_shows_it(client):
    create_project(client)
    payload = {
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    }
    approve = client.post("/projects/p1/edits", json=payload)
    assert approve.status_code == 200
    assert approve.json()["edit_id"] == "e1"

    export = client.post("/projects/p1/export")
    kinds = [(s["kind"]) for s in export.json()["segments"]]
    assert kinds == ["original", "edited", "original"]


def test_approve_rejected_when_continuity_fails(client):
    create_project(client)
    resp = client.post("/projects/p1/edits", json={
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "unknown",
    })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_endpoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api'`.

- [ ] **Step 3: Write the implementation**

`backend/app/api/main.py`:
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.domain.models import Source, Selection, ContinuityReport, EditCandidate, ApprovedEdit
from app.domain.transcript import snap_to_word_boundaries
from app.adapters.mock import MockTranscriptionAdapter, MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.planner import build_edit_plan
from app.orchestrator.pipeline import run_edit
from app.store.repository import ProjectRepository
from app.render.renderer import render

app = FastAPI(title="Agentic Video Editor")

# Wiring (module-level singletons for this in-memory slice).
repo = ProjectRepository()
transcriber = MockTranscriptionAdapter()
voice = MockVoiceAdapter()
lipsync = MockLipSyncAdapter()
continuity = ContinuityEngine()


class CreateProjectRequest(BaseModel):
    filename: str
    duration: float


class EditRequest(BaseModel):
    prompt: str
    start: float
    end: float
    voice_profile_id: str = "speaker-1"


def _continuity_dict(report: ContinuityReport) -> dict:
    return {
        "voice_match": report.voice_match,
        "prosody": report.prosody,
        "audio_integration": report.audio_integration,
        "lip_sync": report.lip_sync,
        "passed": report.passed,
        "warnings": list(report.warnings),
    }


def _candidate_dict(candidate: EditCandidate) -> dict:
    return {
        "plan": {
            "selection": {
                "start": candidate.plan.selection.start,
                "end": candidate.plan.selection.end,
            },
            "new_text": candidate.plan.new_text,
            "voice_profile_id": candidate.plan.voice_profile_id,
        },
        "audio_ref": candidate.audio_ref,
        "frames_ref": candidate.frames_ref,
        "continuity": _continuity_dict(candidate.continuity),
    }


def _build_candidate(project_id: str, req: EditRequest) -> tuple[EditCandidate, object]:
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    plan = build_edit_plan(req.prompt, selection, req.voice_profile_id)
    candidate = run_edit(plan, record.source, voice, lipsync, continuity)
    return candidate, record


@app.post("/projects")
def create_project(req: CreateProjectRequest) -> dict:
    project_id = repo.next_id()
    source = Source(project_id=project_id, filename=req.filename, duration=req.duration)
    transcript = transcriber.transcribe(source)
    repo.create(source, transcript)
    return {
        "project_id": project_id,
        "transcript": [
            {"text": w.text, "start": w.start, "end": w.end} for w in transcript.words
        ],
    }


@app.post("/projects/{project_id}/edits/preview")
def preview_edit(project_id: str, req: EditRequest) -> dict:
    candidate, _ = _build_candidate(project_id, req)
    return _candidate_dict(candidate)


@app.post("/projects/{project_id}/edits")
def approve_edit(project_id: str, req: EditRequest) -> dict:
    candidate, _ = _build_candidate(project_id, req)
    if not candidate.continuity.passed:
        raise HTTPException(status_code=422, detail="continuity check failed")
    edit_id = f"e{len(repo.list_edits(project_id)) + 1}"
    repo.append_edit(project_id, ApprovedEdit(
        edit_id=edit_id,
        plan=candidate.plan,
        audio_ref=candidate.audio_ref,
        frames_ref=candidate.frames_ref,
    ))
    return {"edit_id": edit_id, "continuity": _continuity_dict(candidate.continuity)}


@app.post("/projects/{project_id}/export")
def export_project(project_id: str) -> dict:
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    manifest = render(record.source, repo.list_edits(project_id))
    return {
        "segments": [
            {"start": s.start, "end": s.end, "kind": s.kind, "ref": s.ref}
            for s in manifest.segments
        ],
    }
```

Also create empty `backend/app/api/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_endpoints.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/tests/api
git commit -m "feat: add HTTP API for the edit lifecycle"
```

---

### Task 10: End-to-end journey test + full suite

**Files:**
- Test: `backend/tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_e2e.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.api.main import app, repo


@pytest.fixture(autouse=True)
def reset_repo():
    repo._projects.clear()
    repo._counter = 0
    yield


def test_full_journey_ingest_preview_approve_export():
    client = TestClient(app)

    # 1. Ingest
    created = client.post("/projects", json={"filename": "summer-sale.mp4", "duration": 30.0})
    project_id = created.json()["project_id"]

    # 2. Preview an edit (change the offer)
    payload = {
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    }
    preview = client.post(f"/projects/{project_id}/edits/preview", json=payload).json()
    assert preview["plan"]["new_text"] == "30% off"
    assert preview["continuity"]["passed"] is True

    # 3. Approve it
    approved = client.post(f"/projects/{project_id}/edits", json=payload).json()
    assert approved["edit_id"] == "e1"

    # 4. Export shows the edited span composited between original footage
    segments = client.post(f"/projects/{project_id}/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["start"] == 0.4 and edited[0]["end"] == 1.3
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `cd backend && python -m pytest tests/test_e2e.py -v`
Expected: PASS (the pieces already exist). If it fails, fix the wiring surfaced by the failure before continuing.

- [ ] **Step 3: Run the whole suite**

Run: `cd backend && python -m pytest -v`
Expected: ALL tests pass (Tasks 0–10).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_e2e.py
git commit -m "test: add end-to-end edit journey"
```

---

## Self-Review Notes

- **Spec coverage:** ingest/transcription (Tasks 3, 9), timeline selection + boundary snapping (Task 2, 9), NL prompt → edit plan (Task 5), generation adapters behind swappable interfaces (Task 3), continuity engine with the four checks + thresholds + warnings (Task 4), preview candidate (Task 6, 9), approve → non-destructive stack (Task 7, 9), export/composite (Task 8, 9), iterate loop (deterministic re-preview via the same endpoint). Async job model, real vendors, real ffmpeg render, React UI, and the consent gate are intentionally deferred to later plans (see "Scope of this plan").
- **Type consistency:** `EditPlan(selection, new_text, voice_profile_id)`, `ContinuityReport(voice_match, prosody, audio_integration, lip_sync, passed, warnings)`, `EditCandidate(plan, audio_ref, frames_ref, continuity)`, `ApprovedEdit(edit_id, plan, audio_ref, frames_ref)`, and adapter methods `transcribe`/`synthesize`/`sync` are used identically across every task.
- **No placeholders:** every step has runnable code and exact commands.
