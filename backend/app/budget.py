"""Per-project ceiling on paid voice generation.

Every ElevenLabs attempt — retries included — is charged *before* the call is
made, so a flaky vendor or an agentic retry loop can never spend past the cap.
Charged to the usage ledger (Phase 9b), so the budget survives restarts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.errors import NonRetryableError
from app.usage import Ledger


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
    """ElevenLabs characters per project, read from and charged to the usage
    ledger (Phase 9b) — so the budget survives restarts. A budget without a
    ledger keeps its own, in memory."""

    VENDOR, WHAT, UNIT = "elevenlabs", "speech", "characters"

    def __init__(self, ceiling: int, ledger: Ledger | None = None, usd_per_1k: float = 0.0) -> None:
        self.ceiling = ceiling
        self.ledger = ledger or Ledger()
        self.usd_per_1k = usd_per_1k

    def spent(self, project_id: str) -> int:
        return int(self.ledger.units(project_id, self.VENDOR, self.UNIT))

    def remaining(self, project_id: str) -> int:
        return self.ceiling - self.spent(project_id)

    def can_afford(self, project_id: str, amount: int) -> bool:
        return amount <= self.remaining(project_id)

    def charge(self, project_id: str, amount: int) -> None:
        """Record `amount`, or raise BudgetExceeded and record nothing.

        Check and record happen in one transaction, so concurrent jobs on a
        project can never both squeeze under the ceiling.
        """
        with self.ledger.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(units), 0) AS n FROM usage "
                "WHERE project_id = ? AND vendor = ? AND unit = ?",
                (project_id, self.VENDOR, self.UNIT),
            ).fetchone()
            spent = int(row["n"])
            if spent + amount > self.ceiling:
                raise BudgetExceeded(amount, self.ceiling - spent)
            c.execute(
                "INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, self.VENDOR, self.WHAT, amount, self.UNIT,
                 amount * self.usd_per_1k / 1000, datetime.now(timezone.utc).isoformat()),
            )

    def reset(self) -> None:
        """Forget all spend. Intended for test isolation."""
        with self.ledger.db.tx() as c:
            c.execute("DELETE FROM usage")
