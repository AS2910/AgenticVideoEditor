"""Which voice speaks a line, and making the speaker's own when there is one
to make (Phase 15a).

The precedence for a speaker's line: a voice the user picked for them on
purpose, then their clone, then the voice the request named. A clone is made
once per speaker, lazily at their first line, from all of their own speech, and
every later edit reuses it. When one cannot be made — too little speech, a plan
or key that refuses — the line is spoken in the stock voice and says why, in a
sentence, rather than failing the edit.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection

from app.adapters.base import VendorError
from app.domain.models import MediaArtifact, Source, Transcript
from app.errors import NonRetryableError
from app.media.reference import extract_reference_audio, speech_seconds
from app.store.artifacts import ArtifactStore
from app.store.repository import ProjectRepository

ExtractFn = Callable[..., MediaArtifact | None]


@dataclass(frozen=True)
class VoiceChoice:
    voice_id: str
    # Plain sentences for the candidate: why this is not the speaker's own voice.
    notes: tuple[str, ...] = ()
    cloned: bool = False


class CloneService:
    def __init__(
        self, repo: ProjectRepository, store: ArtifactStore, voice, *,
        enabled: bool = True, min_seconds: float = 10.0, extract: ExtractFn = extract_reference_audio,
    ) -> None:
        self._repo = repo
        self._store = store
        self._voice = voice
        self._enabled = enabled
        self._min = min_seconds
        self._extract = extract
        self._lock = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        # A refusal that retrying cannot fix (a key without the permission, no
        # free slot) is remembered for the run, so every line is not another
        # doomed call; a vendor outage is not remembered.
        self._refused: dict[tuple[str, str], str] = {}
        # (video_id, who) -> an object with done() and fail(text): the clone's Job. None: untracked.
        self.tracker = None

    @property
    def available(self) -> bool:
        return self._enabled and bool(getattr(self._voice, "can_clone", False))

    def _lock_for(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(key, threading.Lock())

    def resolve(self, project_id: str, source: Source, transcript: Transcript,
                speaker: str | None, requested: str) -> VoiceChoice:
        speakers = {s.label: s for s in self._repo.speakers(project_id)}
        chosen = speakers.get(speaker or "")
        if chosen is not None and chosen.voice_id:
            return VoiceChoice(chosen.voice_id)              # picked on purpose: theirs to keep
        if not self.available:
            return VoiceChoice(requested)

        key = speaker or ProjectRepository.WHOLE_CLIP
        who = chosen.name if chosen is not None else "the speaker"
        made = self._repo.clones(project_id).get(key)
        if made:
            self._voice.register_clone(made)
            return VoiceChoice(made, cloned=True)

        with self._lock_for((project_id, key)):
            made = self._repo.clones(project_id).get(key)    # another job may have just made it
            if made:
                self._voice.register_clone(made)
                return VoiceChoice(made, cloned=True)
            if (project_id, key) in self._refused:
                return VoiceChoice(requested, (self._refused[(project_id, key)],))

            have = speech_seconds(transcript, speaker)
            if have < self._min:
                return VoiceChoice(requested, (
                    f"Stock voice: only {have:.1f} s of {who}'s voice, {self._min:.0f} s needed to clone it.",
                ))
            reference = self._extract(
                source, transcript, self._store, speaker=speaker, min_seconds=self._min,
            )
            if reference is None:
                return VoiceChoice(requested, (f"Stock voice: could not cut a clean sample of {who}'s voice.",))
            # One processing model (2026-10-20): the clone is a Job the editor shows.
            track = self.tracker(project_id, who) if self.tracker else None
            try:
                voice_id = self._voice.create_clone(f"voltage-{project_id}-{key}", Path(reference.path))
            except NonRetryableError as exc:
                note = f"Stock voice: could not clone {who}'s voice. {exc}"
                self._refused[(project_id, key)] = note
                if track:
                    track.fail(note)
                return VoiceChoice(requested, (note,))
            except VendorError:
                note = f"Stock voice: ElevenLabs was unavailable when cloning {who}'s voice; the next line will try again."
                if track:
                    track.fail(note)
                return VoiceChoice(requested, (note,))
            except BaseException as exc:
                if track:
                    track.fail(str(exc) or type(exc).__name__)
                raise
            if track:
                track.done()
            self._repo.set_clone(project_id, key, voice_id)
            return VoiceChoice(voice_id, cloned=True)

    def purge(self, project_id: str, keep: Collection[str] = ()) -> list[str]:
        """Delete this project's clones at the vendor (consent withdrawn).
        Returns the voice ids that could not be deleted, for the caller to name.
        A clone in `keep` is one the user kept as their own; it outlives the
        project and is only forgotten here."""
        failed: list[str] = []
        for key, voice_id in self._repo.clones(project_id).items():
            if voice_id in keep:
                self._repo.set_clone(project_id, key, None)
                continue
            try:
                self._voice.delete_clone(voice_id)
            except (VendorError, NonRetryableError):
                failed.append(voice_id)
                continue
            self._repo.set_clone(project_id, key, None)
        self._refused = {k: v for k, v in self._refused.items() if k[0] != project_id}
        return failed
