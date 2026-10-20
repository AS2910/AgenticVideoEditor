"""Feature flags, on per owner (Step 0, FLAGS).

Every phase of the projects plan ships behind one flag; go-live items each
behind `golive.<id>`. A flag is on for an owner when a row in
`feature_flags` says so; with no row, the default is on for the owners named
in AVE_FLAG_OWNERS (default "local", the single owner while sign-in is off)
and off for everyone else. A row always wins over the default, so a flag can
be turned off for a default owner or on for anyone else.
"""
from __future__ import annotations

from app.store.db import Database
from app.timefmt import now_iso

# The phase flags (docs/overnight/PLAN.md, working rule 7).
PHASE_FLAGS = ("projects.consistency", "projects.batch", "projects.review", "projects.reuse")
# Go-live items G1 to G8, each its own flag.
GOLIVE_FLAGS = tuple(f"golive.g{n}" for n in range(1, 9))
KNOWN = PHASE_FLAGS + GOLIVE_FLAGS


def is_known(flag: str) -> bool:
    return flag in KNOWN or flag.startswith("golive.")


class FlagStore:
    def __init__(self, db: Database, default_owners: tuple[str, ...] = ("local",)) -> None:
        self.db = db
        self.default_owners = frozenset(default_owners)

    def _default(self, flag: str, owner: str) -> bool:
        return owner in self.default_owners and is_known(flag)

    def enabled(self, flag: str, owner: str) -> bool:
        """Whether `flag` is on for `owner`."""
        with self.db.tx() as c:
            row = c.execute("SELECT enabled FROM feature_flags WHERE flag = ? AND owner = ?", (flag, owner)).fetchone()
        return bool(row["enabled"]) if row else self._default(flag, owner)

    def set(self, flag: str, owner: str, enabled: bool) -> None:
        """Turn a flag on or off for one owner; overrides the default."""
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO feature_flags (flag, owner, enabled, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (flag, owner) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
                (flag, owner, int(enabled), now_iso()),
            )

    def clear(self, flag: str, owner: str) -> None:
        """Back to the default for this owner."""
        with self.db.tx() as c:
            c.execute("DELETE FROM feature_flags WHERE flag = ? AND owner = ?", (flag, owner))

    def enabled_for(self, owner: str) -> list[str]:
        """Every flag that is on for `owner`, sorted: the known ones by their
        default or row, and any other flag a row turns on."""
        with self.db.tx() as c:
            rows = {r["flag"]: bool(r["enabled"]) for r in c.execute("SELECT flag, enabled FROM feature_flags WHERE owner = ?", (owner,))}
        names = set(KNOWN) | set(rows)
        return sorted(n for n in names if rows.get(n, self._default(n, owner)))
