"""Per-video ceiling on paid voice generation.

Every ElevenLabs attempt — retries included — is charged *before* the call is
made, so a flaky vendor or an agentic retry loop can never spend past the cap.
Charged to the usage ledger (Phase 9b), so the budget survives restarts.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

from app.timefmt import now_iso

from datetime import datetime, timezone

from app.errors import NonRetryableError
from app.store.workspaces import stamp_last
from app.usage import Ledger, current_actor, folder_of


class BudgetExceeded(NonRetryableError):
    """The video cannot afford this call."""

    def __init__(self, needed: int, remaining: int) -> None:
        self.needed = needed
        self.remaining = remaining
        super().__init__(
            f"This video's voice budget can't cover this edit: it needs {needed} "
            f"characters and {remaining} remain. Raise AVE_VOICE_BUDGET_CHARS to continue."
        )


log = logging.getLogger("voltage.budget")
# Rehearsal item 4 (the crash drill): which process holds an open charge. A
# charge made before a vendor call stays "open" in meta until the call has
# returned or been refunded; one a dead process left open is given back at the
# next start (`refund_orphans`), so a crash mid-call never bills a take that
# was never made (and a retry does not pay twice).
PROCESS = uuid.uuid4().hex
OPEN_PREFIX = "charge_open:"


class VoiceBudget:
    """ElevenLabs characters per video, read from and charged to the usage
    ledger (Phase 9b) — so the budget survives restarts. A budget without a
    ledger keeps its own, in memory."""

    VENDOR, WHAT, UNIT = "elevenlabs", "speech", "characters"

    def __init__(self, ceiling: int, ledger: Ledger | None = None, usd_per_1k: float = 0.0) -> None:
        self.ceiling = ceiling
        self.ledger = ledger or Ledger()
        self.usd_per_1k = usd_per_1k
        # Launch item 3: asked before every charge; raises to refuse (the global pause).
        self.before_charge: Callable[[], None] | None = None

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
        if self.before_charge is not None:
            self.before_charge()
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
                "INSERT INTO usage (project_id, vendor, what, units, unit, usd, at, folder_id, by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, self.VENDOR, self.WHAT, amount, self.UNIT,
                 amount * self.usd_per_1k / 1000, now_iso(), folder_of(c, project_id), current_actor.get()),
            )
            stamp_last(c, "usage", project_id)
        self.ledger._after(project_id, None)          # G4: spend alerts

    def refund(self, project_id: str, amount: int) -> None:
        """Give back a charge for a call that failed before anything was made
        (the chaos pass): the ledger is append-only, so a negative row. The
        budget's accounting stays exact; a 429 storm no longer eats the cap."""
        if amount <= 0:
            return
        self.ledger.record(project_id, self.VENDOR, self.WHAT, -amount, self.UNIT,
                           -amount * self.usd_per_1k / 1000)

    @contextmanager
    def held(self, project_id: str, amount: int) -> Iterator[None]:
        """Charge `amount` for one vendor call: refunded if anything inside raises,
        and marked open in meta while the call runs (see PROCESS)."""
        self.charge(project_id, amount)
        key = OPEN_PREFIX + uuid.uuid4().hex
        with self.ledger.db.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?)",
                      (key, json.dumps({"project_id": project_id, "amount": amount, "process": PROCESS, "at": now_iso()})))
        try:
            yield
        except BaseException:
            self.refund(project_id, amount)
            raise
        finally:
            with self.ledger.db.tx() as c:
                c.execute("DELETE FROM meta WHERE key = ?", (key,))

    def refund_orphans(self) -> list[dict]:
        """At startup: give back every charge a previous process left open (it
        died during the call, so nothing it paid for was kept). Returns them."""
        with self.ledger.db.tx() as c:
            rows = c.execute("SELECT key, value FROM meta WHERE key LIKE ?", (OPEN_PREFIX + "%",)).fetchall()
        given = []
        for r in rows:
            try:
                held = json.loads(r["value"])
            except (TypeError, ValueError):
                held = {}
            if held.get("process") == PROCESS:
                continue
            if held.get("project_id") and int(held.get("amount") or 0) > 0:
                self.refund(held["project_id"], int(held["amount"]))
                given.append(held)
                log.warning("refunded %s characters on %s: the process that charged them stopped during the call",
                            held["amount"], held["project_id"])
            with self.ledger.db.tx() as c:
                c.execute("DELETE FROM meta WHERE key = ?", (r["key"],))
        return given

    def reset(self) -> None:
        """Forget all spend. Intended for test isolation."""
        with self.ledger.db.tx() as c:
            c.execute("DELETE FROM usage")
