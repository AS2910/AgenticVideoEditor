"""What each project has spent on paid vendors (Phase 9b).

Every paid call is one row in the `usage` table: vendor, units, and an
estimated USD cost. The ledger is the single source for both the per-project
spend ceiling and the ElevenLabs character budget, so both survive restarts.

USD is an estimate from list prices, not an invoice: ElevenLabs bills by plan
(the free tier costs nothing but has a quota), so its rate is configurable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.errors import NonRetryableError
from app.store.db import Database

# List prices used for the estimates.
WHISPER_USD_PER_MINUTE = 0.006
CLAUDE_USD_PER_MTOK = {"claude-opus-5": (5.00, 25.00)}   # (input, output)


def claude_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    per_in, per_out = CLAUDE_USD_PER_MTOK.get(model, (5.00, 25.00))
    return (input_tokens * per_in + output_tokens * per_out) / 1_000_000


class SpendCeilingReached(NonRetryableError):
    """The project has spent its allowance; no new paid work starts."""

    def __init__(self, spent: float, ceiling: float) -> None:
        self.spent, self.ceiling = spent, ceiling
        super().__init__(
            f"This project has used its ${ceiling:.2f} spending limit "
            f"(about ${spent:.2f} so far). Raise AVE_PROJECT_BUDGET_USD to continue."
        )


@dataclass(frozen=True)
class UsageLine:
    vendor: str
    what: str
    unit: str
    units: float
    usd: float
    calls: int


class Ledger:
    def __init__(self, db: Database | None = None, ceiling_usd: float = 2.0) -> None:
        self.db = db or Database()
        self.ceiling_usd = ceiling_usd

    def record(
        self, project_id: str, vendor: str, what: str, units: float, unit: str, usd: float,
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, vendor, what, units, unit, usd, datetime.now(timezone.utc).isoformat()),
            )

    def spent_usd(self, project_id: str) -> float:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(usd), 0) AS usd FROM usage WHERE project_id = ?", (project_id,),
            ).fetchone()
        return float(row["usd"])

    def units(self, project_id: str, vendor: str, unit: str) -> float:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(units), 0) AS n FROM usage "
                "WHERE project_id = ? AND vendor = ? AND unit = ?", (project_id, vendor, unit),
            ).fetchone()
        return float(row["n"])

    def lines(self, project_id: str) -> list[UsageLine]:
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT vendor, what, unit, SUM(units) AS units, SUM(usd) AS usd, COUNT(*) AS calls "
                "FROM usage WHERE project_id = ? GROUP BY vendor, what, unit ORDER BY vendor, what",
                (project_id,),
            ).fetchall()
        return [UsageLine(r["vendor"], r["what"], r["unit"], r["units"], r["usd"], r["calls"]) for r in rows]

    def ensure_can_spend(self, project_id: str) -> None:
        """Refuse new paid work once the project has reached its ceiling."""
        spent = self.spent_usd(project_id)
        if spent >= self.ceiling_usd:
            raise SpendCeilingReached(spent, self.ceiling_usd)
