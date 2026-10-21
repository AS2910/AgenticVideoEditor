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
# Launch switches (item 1 of the launch plan). Off for everyone by default,
# the default owners included; they are usually set for everyone at once
# with the owner `*` (`FlagStore.set(flag, ALL, True)`).
LAUNCH_FLAGS = ("launch.invite_only", "launch.paid_paused")
KNOWN = PHASE_FLAGS + GOLIVE_FLAGS + LAUNCH_FLAGS
# The owner a row names to set a flag for everyone. An owner's own row still wins.
ALL = "*"


def is_known(flag: str) -> bool:
    return flag in KNOWN or flag.startswith(("golive.", "launch."))


class FlagStore:
    def __init__(self, db: Database, default_owners: tuple[str, ...] = ("local",)) -> None:
        self.db = db
        self.default_owners = frozenset(default_owners)

    def _default(self, flag: str, owner: str) -> bool:
        return owner in self.default_owners and is_known(flag) and not flag.startswith("launch.")

    def enabled(self, flag: str, owner: str = ALL) -> bool:
        """Whether `flag` is on for `owner`: their own row, else the row for
        everyone (`*`), else the default."""
        with self.db.tx() as c:
            rows = {r["owner"]: r["enabled"] for r in c.execute(
                "SELECT owner, enabled FROM feature_flags WHERE flag = ? AND owner IN (?, ?)", (flag, owner, ALL))}
        if owner in rows:
            return bool(rows[owner])
        if ALL in rows:
            return bool(rows[ALL])
        return self._default(flag, owner)

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
            everyone = {r["flag"]: bool(r["enabled"]) for r in c.execute("SELECT flag, enabled FROM feature_flags WHERE owner = ?", (ALL,))}
            rows = {r["flag"]: bool(r["enabled"]) for r in c.execute("SELECT flag, enabled FROM feature_flags WHERE owner = ?", (owner,))}
        names = set(KNOWN) | set(everyone) | set(rows)
        return sorted(n for n in names if rows.get(n, everyone.get(n, self._default(n, owner))))


def main(argv: list[str] | None = None) -> int:
    """`python -m app.flags set launch.invite_only on --db var/ave.db [--owner '*']`,
    `... clear <flag> --db ...`, `... show --db ... [--owner local]`."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m app.flags", description="Turn feature flags on or off.")
    parser.add_argument("command", choices=("set", "clear", "show"))
    parser.add_argument("flag", nargs="?")
    parser.add_argument("value", nargs="?", choices=("on", "off"))
    parser.add_argument("--owner", default=ALL, help="an owner id, or * for everyone (default)")
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    store = FlagStore(Database(args.db))
    if args.command == "set":
        if not args.flag or not args.value:
            parser.error("set needs a flag and on or off")
        store.set(args.flag, args.owner, args.value == "on")
    elif args.command == "clear":
        if not args.flag:
            parser.error("clear needs a flag")
        store.clear(args.flag, args.owner)
    for flag in store.enabled_for(args.owner):
        print(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
