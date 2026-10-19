"""What each video has spent on paid vendors (Phase 9b).

Every paid call is one row in the `usage` table: vendor, units, and an
estimated USD cost. The ledger is the single source for both the per-video
spend ceiling and the ElevenLabs character budget, so both survive restarts.
Folders: a row also carries `folder_id`, the project the video was in at the
time of the charge, so a project's spend is a sum over its own rows.

USD is an estimate from list prices, not an invoice: ElevenLabs bills by plan
(the free tier costs nothing but has a quota), so its rate is configurable.
"""
from __future__ import annotations

from app.timefmt import now_iso

from dataclasses import dataclass
from datetime import datetime, timezone

from app.errors import NonRetryableError
from app.store.db import Database

# List prices used for the estimates.
WHISPER_USD_PER_MINUTE = 0.006
CLAUDE_USD_PER_MTOK = {"claude-opus-5": (5.00, 25.00)}   # (input, output)


# Prompt caching: a cached read is a tenth of the input rate, writing the
# cache a quarter more (the 5-minute cache).
CACHE_READ, CACHE_WRITE = 0.10, 1.25


def claude_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    per_in, per_out = CLAUDE_USD_PER_MTOK.get(model, (5.00, 25.00))
    return (input_tokens * per_in + cache_read * per_in * CACHE_READ + cache_write * per_in * CACHE_WRITE
            + output_tokens * per_out) / 1_000_000


class SpendCeilingReached(NonRetryableError):
    """The video has spent its allowance; no new paid work starts."""

    def __init__(self, spent: float, ceiling: float) -> None:
        self.spent, self.ceiling = spent, ceiling
        super().__init__(
            f"This video has used its ${ceiling:.2f} spending limit "
            f"(about ${spent:.2f} so far). Raise AVE_PROJECT_BUDGET_USD to continue."
        )


class UserCeilingReached(SpendCeilingReached):
    """The person has spent their allowance across every video."""

    def __init__(self, spent: float, ceiling: float) -> None:
        self.spent, self.ceiling = spent, ceiling
        NonRetryableError.__init__(
            self,
            f"You have used your ${ceiling:.2f} spending limit across your videos "
            f"(about ${spent:.2f} so far).",
        )


class ProjectCeilingReached(SpendCeilingReached):
    """The project (folder) has spent the ceiling set on it (Folders)."""

    def __init__(self, spent: float, ceiling: float, name: str = "") -> None:
        self.spent, self.ceiling = spent, ceiling
        NonRetryableError.__init__(
            self,
            f"The project{f' {name}' if name else ''} has used its ${ceiling:.2f} spending ceiling "
            f"(about ${spent:.2f} so far). Raise it on the project page to continue.",
        )


def folder_of(c, project_id: str) -> str | None:
    """The project (folder) a video is in now, read inside the caller's
    transaction, so a charge carries it."""
    row = c.execute("SELECT project_id FROM videos WHERE id = ?", (project_id,)).fetchone()
    return row["project_id"] if row else None


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
                "INSERT INTO usage (project_id, vendor, what, units, unit, usd, at, folder_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, vendor, what, units, unit, usd, now_iso(),
                 folder_of(c, project_id)),
            )

    def spent_usd(self, project_id: str) -> float:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(usd), 0) AS usd FROM usage WHERE project_id = ?", (project_id,),
            ).fetchone()
        return float(row["usd"])

    def spent_usd_since(self, project_id: str, at: str, vendor: str | None = None) -> float:
        """What one plan or turn cost: everything recorded since `at`, or
        one vendor's share of it (20d: Voltage's own thinking is "anthropic")."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(usd), 0) AS usd FROM usage WHERE project_id = ? AND at >= ?"
                + (" AND vendor = ?" if vendor else ""),
                (project_id, at) + ((vendor,) if vendor else ()),
            ).fetchone()
        return float(row["usd"])

    def calls_since(self, project_id: str, vendor: str, at: str) -> int:
        """How many calls one vendor made good since `at` — for ElevenLabs, the
        takes a plan voiced: every take is charged as its own row, and a call
        that failed before anything was made is refunded as a negative row,
        which cancels its charge here (the chaos pass)."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(CASE WHEN units > 0 THEN 1 WHEN units < 0 THEN -1 ELSE 0 END), 0) AS n "
                "FROM usage WHERE project_id = ? AND vendor = ? AND at >= ?",
                (project_id, vendor, at),
            ).fetchone()
        return int(row["n"])

    def units(self, project_id: str, vendor: str, unit: str) -> float:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(units), 0) AS n FROM usage "
                "WHERE project_id = ? AND vendor = ? AND unit = ?", (project_id, vendor, unit),
            ).fetchone()
        return float(row["n"])

    def lines(self, project_id: str, since: str | None = None) -> list[UsageLine]:
        """What the project spent, per vendor and purpose; with `since`, only
        the rows from that moment on (the Usage page's week or month)."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT vendor, what, unit, SUM(units) AS units, SUM(usd) AS usd, SUM(CASE WHEN units > 0 THEN 1 WHEN units < 0 THEN -1 ELSE 0 END) AS calls "
                "FROM usage WHERE project_id = ?" + (" AND at >= ?" if since else "")
                + " GROUP BY vendor, what, unit ORDER BY vendor, what",
                (project_id,) + ((since,) if since else ()),
            ).fetchall()
        return [UsageLine(r["vendor"], r["what"], r["unit"], r["units"], r["usd"], r["calls"]) for r in rows]

    def spent_usd_by_owner(self, owner: str) -> float:
        """Everything one person's videos have spent (Phase 9c)."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(u.usd), 0) AS usd FROM usage u "
                "JOIN videos v ON v.id = u.project_id WHERE v.owner = ?", (owner,),
            ).fetchone()
        return float(row["usd"])

    def spent_usd_by_folder(self, folder_id: str, since: str | None = None) -> float:
        """What a project's videos spent while in it (Folders)."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(usd), 0) AS usd FROM usage WHERE folder_id = ?" + (" AND at >= ?" if since else ""),
                (folder_id,) + ((since,) if since else ()),
            ).fetchone()
        return float(row["usd"])

    def ensure_can_spend(self, project_id: str, owner: str | None = None,
                         owner_ceiling_usd: float | None = None, folder: tuple[str, float, str] | None = None) -> None:
        """Refuse new paid work once the video — or its project (`folder` =
        (id, ceiling, name)), or with sign-in the person — has reached its
        ceiling. Every ceiling applies; the lowest wins."""
        spent = self.spent_usd(project_id)
        if spent >= self.ceiling_usd:
            raise SpendCeilingReached(spent, self.ceiling_usd)
        if folder is not None:
            folder_id, ceiling, name = folder
            ours = self.spent_usd_by_folder(folder_id)
            if ours >= ceiling:
                raise ProjectCeilingReached(ours, ceiling, name)
        if owner is not None and owner_ceiling_usd is not None:
            mine = self.spent_usd_by_owner(owner)
            if mine >= owner_ceiling_usd:
                raise UserCeilingReached(mine, owner_ceiling_usd)
