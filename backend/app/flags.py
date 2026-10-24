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
PHASE_FLAGS = ("projects.consistency", "projects.batch", "projects.review", "projects.reuse",
               # Launch item 10: A2 (the project check) apart from A1 and A3.
               "projects.check")
# Go-live items G1 to G8, each its own flag.
GOLIVE_FLAGS = tuple(f"golive.g{n}" for n in range(1, 9))
# Launch switches (item 1 of the launch plan). Off for everyone by default,
# the default owners included; they are usually set for everyone at once
# with the owner `*` (`FlagStore.set(flag, ALL, True)`).
LAUNCH_FLAGS = ("launch.invite_only", "launch.paid_paused")
# Rehearsal item 1 (launch blocker 4): cloning a voice (your own, or a
# speaker's) waits for a real liveness check. On for the default owners, not
# in the public profile; an admin turns it on per person (Features).
# Run 4 item 2: voices.cloning_verified opens cloning a video's speaker once
# their consent check passes (app.safety.consent: the phrase, the words, the
# voice). Off for everyone by default, the default owners too, and not in the
# public profile: the person who runs Voltage turns it on (for `*`, or per
# owner). It needs golive.g6 (the read-aloud step). It does not open cloning
# your own voice from an upload; voices.cloning still does that.
VOICE_FLAGS = ("voices.cloning", "voices.cloning_verified")
OFF_BY_DEFAULT = frozenset({"voices.cloning_verified"})
KNOWN = PHASE_FLAGS + GOLIVE_FLAGS + LAUNCH_FLAGS + VOICE_FLAGS
# The owner a row names to set a flag for everyone. An owner's own row still wins.
ALL = "*"
# Launch item 10: AVE_LAUNCH_PROFILE=public turns these on for everyone: the
# core editor and folders (never flagged), A1 and A3 (projects.consistency),
# G1 to G4 and G6 to G8 (the admin page itself stays admins only). Phases B,
# C, D and A2 stay off, and so does voices.cloning; an admin turns them on per
# owner (a row).
PROFILES = {
    "public": frozenset({"projects.consistency", "golive.g1", "golive.g2", "golive.g3", "golive.g4",
                         "golive.g6", "golive.g7", "golive.g8"}),
}


def is_known(flag: str) -> bool:
    return flag in KNOWN or flag.startswith(("golive.", "launch."))


class FlagStore:
    def __init__(self, db: Database, default_owners: tuple[str, ...] = ("local",), profile: str | None = None) -> None:
        self.db = db
        self.default_owners = frozenset(default_owners)
        self.profile = PROFILES.get(profile or "", frozenset())

    def _default(self, flag: str, owner: str) -> bool:
        if flag.startswith("launch.") or flag in OFF_BY_DEFAULT or not is_known(flag):
            return False
        return owner in self.default_owners or flag in self.profile

    def explain(self, owner: str) -> list[dict]:
        """Every known flag for `owner`: on or off, and why (their row, everyone's row, the profile or the default)."""
        with self.db.tx() as c:
            rows = {(r["flag"], r["owner"]): bool(r["enabled"]) for r in c.execute(
                "SELECT flag, owner, enabled FROM feature_flags WHERE owner IN (?, ?)", (owner, ALL))}
        out = []
        for flag in KNOWN:
            if (flag, owner) in rows:
                on, source = rows[(flag, owner)], "owner"
            elif (flag, ALL) in rows:
                on, source = rows[(flag, ALL)], "everyone"
            else:
                on = self._default(flag, owner)
                source = "default_owner" if owner in self.default_owners and on else ("profile" if on else "off")
            out.append({"flag": flag, "on": on, "source": source})
        return out

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
    parser.add_argument("command", choices=("set", "clear", "show", "profile"))
    parser.add_argument("flag", nargs="?")
    parser.add_argument("value", nargs="?", choices=("on", "off"))
    parser.add_argument("--owner", default=ALL, help="an owner id, or * for everyone (default)")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    if args.command == "profile":
        name = args.flag or "public"
        print(f"AVE_LAUNCH_PROFILE={name} turns on for everyone:")
        for flag in sorted(PROFILES.get(name, ())):
            print(f"  on   {flag}")
        for flag in sorted(set(KNOWN) - PROFILES.get(name, frozenset())):
            print(f"  off  {flag}")
        return 0
    if not args.db:
        parser.error("--db is required")
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
