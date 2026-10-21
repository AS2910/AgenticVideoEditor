"""G7: event tracking for every key step, and the numbers the admin page reads.

    track(name, owner, props=None)            one event, in its own transaction
    track_in(c, name, owner, props=None)      one event, in the caller's transaction
    funnel(db) / take_acceptance(db) / cost_per_exported_minute(db) / counts(db) / vendor_quality(db)

Every event lands in `analytics_events` (migration 0026): its name, the owner
it belongs to, the workspace, JSON props, whether the server or the client
sent it, and when. Names come from an allow-list: SERVER_NAMES are written
where the action happens (every F7 activity-log verb is mirrored by
`app.store.events.record`, in the same transaction), CLIENT_NAMES may also be
posted by the browser through `POST /analytics/events`. An unknown name is
refused, so a typo never becomes a new metric. `track` never raises: a lost
event never breaks the work it describes.

The funnel's "first" steps (`signed_up`, `first_sign_in`, `first_turn`,
`first_export`) are written once per owner. No number here is invented: a
rate with nothing under it is None, and SIM-o and UTMOS appear only where a
take's score was measured from the media.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from app.store.db import Database
from app.timefmt import now_iso

log = logging.getLogger(__name__)

# The core funnel, in order (sign-up to first export).
FUNNEL = (("signed_up", "Signed up"), ("first_sign_in", "Signed in"), ("video_uploaded", "Uploaded a video"),
          ("first_turn", "Asked Voltage"), ("take_voiced", "Got a take"), ("take_added", "Added a take"),
          ("first_export", "Exported"))
# Written at most once per owner.
ONCE = frozenset({"signed_up", "first_sign_in", "first_turn", "first_export"})

# The F7 activity-log verbs (mirrored from app.store.events.record) and the
# other server-side names each item listed in PROGRESS.md.
F7_VERBS = frozenset({
    "brief.saved", "rule.added", "rule.changed", "rule.removed", "stage.moved", "video.moved_in", "video.moved_out",
    "edit.shipped", "edit.undone", "video.deleted", "video.restored", "project.deleted", "project.restored",
    "brief.update_started", "brief.video_current", "brief.update_finished",
    "check.started", "check.finished", "check.issue_ignored", "check.fix_started", "check.fix_all_started",
    "check.fix_all_finished",
    "batch.planned", "batch.started", "batch.finished", "batch.cancelled", "batch.answered", "batch.added_all",
    "batch.add_undone",
    "share.created", "share.revoked",
    "export_preset.added", "export_preset.changed", "export_preset.removed", "export.started", "export.finished",
    "language.versions_made", "language.sync_started", "language.synced",
    "review.commented", "review.approved", "review.changes_asked", "review.replied", "review.resolved",
    "review.reopened",
    "project.archived", "project.unarchived",
    "template.saved", "template.renamed", "template.deleted", "project.from_template",
    "learned.suggested", "learned.accepted", "learned.dismissed", "learned.removed",
    "member.invited", "member.joined", "member.changed", "member.removed",
    "consent.withdrawn",
})
SERVER_NAMES = F7_VERBS | frozenset({
    # The funnel and its measures.
    *(n for n, _ in FUNNEL), "video_exported",
    # A3 words; D3 voices; B3/F6 shares and exports; C2 email; G1; G4.
    "words.clip_added", "words.learned_from_transcript", "take.word_rule_broken", "take.word_rule_warned",
    # Launch items 2 and 3.
    "rate_limited", "paid.paused_refusal", "paid.switch",
    # Launch item 5.
    "account.created", "account.verified", "account.password_reset", "account.email_changed",
    "voice.restored", "share.opened", "export.file_failed", "export.zip_downloaded",
    "notify.digest_sent", "notify.version_ready_sent", "notify.review_invite_sent",
    "sample.created", "sample.skipped", "import.started", "import.finished", "import.failed",
    "notification.created", "notification.read", "notification.settings_changed",
    # G8: thumbs on takes and turns.
    "feedback.given",
    # G3: billing (fake providers): a plan bought, a top-up, paid work paused for credits.
    "billing.plan_changed", "billing.topped_up", "billing.credits_out", "billing.refunded",
    # G6: trust and safety.
    "consent.liveness_checked", "consent.withdrawn", "clone.public_figure_refused", "abuse.reported",
    "data.export_requested", "data.export_ready", "data.deletion_requested", "export.provenance_stamped",
})
# What the browser may post (and nothing else).
CLIENT_NAMES = frozenset({
    "line.banned_word_warned",
    "board.opened", "board.card_moved", "stage.add_anyway", "stage.add_cancelled", "feed.older_loaded",
    "review.link_copied", "review.turn_started", "review.page_opened",
    "bin.opened", "bin.restored",
    "search.opened", "search.result_opened", "pin.added", "pin.removed", "home.sorted", "home.filtered",
    "template.dialog_opened", "template.start_from_picked", "templates.opened",
    "proposal.discard_reason_given", "learned.card_opened",
    "import.link_pasted", "members.opened", "invite.opened", "signin.email_requested",
    "bell.opened", "bell.item_opened",
    "admin.opened", "billing.opened", "legal.opened",
})
NAMES = SERVER_NAMES | CLIENT_NAMES
MAX_PROPS = 2000                # bytes of JSON kept per event

_db: Database | None = None


def configure(db: Database) -> None:
    """The database `track` writes to (the app's, set once at start)."""
    global _db
    _db = db


def _props(props: dict | None) -> str:
    text = json.dumps(props or {}, default=str)
    return text if len(text) <= MAX_PROPS else json.dumps({"truncated": True})


def _workspace(c: sqlite3.Connection, owner: str) -> str | None:
    row = c.execute("SELECT id FROM workspaces WHERE owner = ? ORDER BY created_at LIMIT 1", (owner,)).fetchone()
    return row[0] if row else None


def track_in(c: sqlite3.Connection, name: str, owner: str | None, props: dict | None = None, *,
             source: str = "server", workspace_id: str | None = None) -> bool:
    """Write one event in the caller's transaction. False when it was not
    written: an unknown name, no owner, or a once-only step already there."""
    if name not in NAMES or not owner:
        return False
    if name in ONCE and c.execute("SELECT 1 FROM analytics_events WHERE name = ? AND owner = ? LIMIT 1",
                                  (name, owner)).fetchone():
        return False
    c.execute("INSERT INTO analytics_events (workspace_id, owner, name, props, source, at) VALUES (?, ?, ?, ?, ?, ?)",
              (workspace_id or _workspace(c, owner), owner, name, _props(props), source, now_iso()))
    return True


def track(name: str, owner: str | None, props: dict | None = None, *, source: str = "server",
          db: Database | None = None) -> bool:
    """Write one event in its own transaction; never raises."""
    target = db or _db
    if target is None:
        return False
    try:
        with target.tx() as c:
            return track_in(c, name, owner, props, source=source)
    except Exception:  # noqa: BLE001 - an event never breaks the work it describes
        log.exception("analytics event %s", name)
        return False


def safe_in(c: sqlite3.Connection, name: str, owner: str | None, props: dict | None = None, **kw) -> None:
    """`track_in` that never raises (a missing table on an old database, a bad prop)."""
    try:
        c.execute("SAVEPOINT analytics")
        track_in(c, name, owner, props, **kw)
        c.execute("RELEASE analytics")
    except Exception:  # noqa: BLE001
        try:
            c.execute("ROLLBACK TO analytics")
            c.execute("RELEASE analytics")
        except Exception:  # noqa: BLE001
            pass
        log.exception("analytics event %s", name)


# ── the admin page's numbers ─────────────────────────────────────────────────

def counts(db: Database) -> list[dict]:
    """Every name seen, with how many events and how many owners, most first."""
    with db.tx() as c:
        rows = c.execute("SELECT name, source, COUNT(*) AS n, COUNT(DISTINCT owner) AS owners, MAX(at) AS last "
                         "FROM analytics_events GROUP BY name, source ORDER BY n DESC, name").fetchall()
    return [{"name": r["name"], "source": r["source"], "count": r["n"], "owners": r["owners"], "last": r["last"]} for r in rows]


def funnel(db: Database) -> list[dict]:
    """Owners who reached each step, in order; `share` is of the first step (None when nobody signed up)."""
    with db.tx() as c:
        reached = {r["name"]: r["owners"] for r in c.execute(
            "SELECT name, COUNT(DISTINCT owner) AS owners FROM analytics_events WHERE name IN (%s) GROUP BY name"
            % ",".join("?" * len(FUNNEL)), [n for n, _ in FUNNEL])}
    top = reached.get(FUNNEL[0][0], 0)
    return [{"step": n, "label": label, "owners": reached.get(n, 0),
             "share": (reached.get(n, 0) / top) if top else None} for n, label in FUNNEL]


def take_acceptance(db: Database) -> dict:
    """Takes added over takes voiced; `rate` is None until a take was voiced."""
    with db.tx() as c:
        voiced = c.execute("SELECT COUNT(*) FROM analytics_events WHERE name = 'take_voiced'").fetchone()[0]
        added = c.execute("SELECT COUNT(*) FROM analytics_events WHERE name = 'take_added'").fetchone()[0]
    return {"voiced": voiced, "added": added, "rate": (added / voiced) if voiced else None}


def cost_per_exported_minute(db: Database) -> dict:
    """Every charge in the ledger over the minutes exported (from `video_exported`);
    `per_minute` is None until something was exported."""
    with db.tx() as c:
        cost = float(c.execute("SELECT COALESCE(SUM(usd), 0) FROM usage").fetchone()[0] or 0.0)
        seconds = 0.0
        for (props,) in c.execute("SELECT props FROM analytics_events WHERE name = 'video_exported'"):
            try:
                seconds += float(json.loads(props or "{}").get("seconds") or 0.0)
            except (TypeError, ValueError):
                continue
    minutes = seconds / 60.0
    return {"cost_usd": round(cost, 4), "minutes": round(minutes, 3),
            "per_minute": round(cost / minutes, 4) if minutes > 0 else None}


def vendor_quality(db: Database) -> list[dict]:
    """SIM-o and UTMOS per voice vendor, only from takes whose scores were
    measured (the `take_voiced` props carry them only then). A vendor with
    takes but no measured score says so (`measured: False`); nothing is made up."""
    found: dict[str, dict] = {}
    with db.tx() as c:
        for (props,) in c.execute("SELECT props FROM analytics_events WHERE name = 'take_voiced'"):
            try:
                p = json.loads(props or "{}")
            except ValueError:
                continue
            v = found.setdefault(str(p.get("vendor") or "unknown"), {"takes": 0, "sim_o": [], "utmos": []})
            v["takes"] += 1
            for key in ("sim_o", "utmos"):
                if isinstance(p.get(key), (int, float)):
                    v[key].append(float(p[key]))
    out = []
    for vendor, v in sorted(found.items()):
        mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
        out.append({"vendor": vendor, "takes": v["takes"], "sim_o": mean(v["sim_o"]), "sim_o_takes": len(v["sim_o"]),
                    "utmos": mean(v["utmos"]), "utmos_takes": len(v["utmos"]),
                    "measured": bool(v["sim_o"] or v["utmos"])})
    return out
