"""The voice vendor for the launch rehearsal (AVE_MOCK_VENDORS=1).

The mock's tone, but billed and timed like ElevenLabs: each line charges its
characters times the takes per line to the project's budget before it is
voiced (so the ledger, the credits and the spend alerts move as they would),
waits AVE_MOCK_SYNTH_SECONDS (default "2-6"), and gives the charge back when
it fails. AVE_CHAOS's `elevenlabs=` faults apply here too, so the failure
drills reach the same retry and refund paths: `status:5xx` and 429 are worth
retrying, other statuses are a refusal; `hang` waits then times out;
`refuse` is the vendor's safety filter refusing the line (run 5 item 1).
"""
from __future__ import annotations

import time

from app.adapters.elevenlabs import VoiceConfigError, VoiceError, _raise_for
from app.chaos import CHAOS_REFUSAL
from app.adapters.mock import MockVoiceAdapter
from app.adapters.mock_claude import wait
from app.budget import VoiceBudget
from app.chaos import Chaos
from app.domain.models import EditPlan, MediaArtifact, Source, Transcript
from app.store.artifacts import ArtifactStore


class RehearsalVoiceAdapter(MockVoiceAdapter):
    identity = "mock"

    def __init__(self, store: ArtifactStore, budget: VoiceBudget, chaos: Chaos | None = None, takes_per_line: int = 1) -> None:
        super().__init__(store)
        self._budget = budget
        self._chaos = chaos
        self._takes = max(1, takes_per_line)

    def cost_of(self, plan: EditPlan) -> int:
        return len(plan.new_text or "") * self._takes

    def _fault(self, plan: EditPlan | None = None) -> None:
        f = self._chaos._fault("elevenlabs") if self._chaos else None
        if f is None:
            return
        line = (plan.new_text, plan.selection.start) if plan is not None else None
        if f.kind == "status":
            _raise_for(int(f.arg), f'{{"detail": "chaos: injected {int(f.arg)}"}}', line)
        if f.kind == "refuse":
            _raise_for(400, CHAOS_REFUSAL, line)
        if f.kind == "hang":
            time.sleep(f.arg)
            raise VoiceError("Could not reach ElevenLabs (ReadTimeout).")
        if f.kind == "slow":
            time.sleep(f.arg)
            return
        raise VoiceError("Could not reach ElevenLabs (ConnectError).")

    def synthesize(self, source: Source, plan: EditPlan, transcript: Transcript | None = None) -> MediaArtifact:
        with self._budget.held(source.project_id, self.cost_of(plan)):   # as the ElevenLabs adapter charges
            self._fault(plan)
            wait("AVE_MOCK_SYNTH_SECONDS", "2-6")
            return super().synthesize(source, plan, transcript)
