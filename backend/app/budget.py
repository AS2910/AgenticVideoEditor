"""Per-project ceiling on paid voice generation.

Every ElevenLabs attempt — retries included — is charged *before* the call is
made, so a flaky vendor or an agentic retry loop can never spend past the cap.
In memory like the rest of the project state until Phase 9: a restart resets it.
"""
from __future__ import annotations

import threading

from app.errors import NonRetryableError


class BudgetExceeded(NonRetryableError):
    """The project cannot afford this call."""

    def __init__(self, needed: int, remaining: int) -> None:
        self.needed = needed
        self.remaining = remaining
        super().__init__(
            f"This project's voice budget can't cover this edit: it needs {needed} "
            f"characters and {remaining} remain. Raise AVE_VOICE_BUDGET_CHARS to continue."
        )


class VoiceBudget:
    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        self._spent: dict[str, int] = {}
        self._lock = threading.Lock()

    def spent(self, project_id: str) -> int:
        with self._lock:
            return self._spent.get(project_id, 0)

    def remaining(self, project_id: str) -> int:
        return self.ceiling - self.spent(project_id)

    def can_afford(self, project_id: str, amount: int) -> bool:
        return amount <= self.remaining(project_id)

    def charge(self, project_id: str, amount: int) -> None:
        """Record `amount`, or raise BudgetExceeded and record nothing."""
        with self._lock:
            spent = self._spent.get(project_id, 0)
            if spent + amount > self.ceiling:
                raise BudgetExceeded(amount, self.ceiling - spent)
            self._spent[project_id] = spent + amount

    def reset(self) -> None:
        """Forget all spend. Intended for test isolation."""
        with self._lock:
            self._spent.clear()
