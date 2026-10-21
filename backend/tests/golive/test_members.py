"""G2 store: roles, signed invites, one-use login links, the role matrix,
the member limit in the spend guard, migration 0024 up and down."""
import pytest

from app.store import members as m, migrate
from app.store.db import Database
from app.usage import Ledger, MemberLimitReached, current_actor
from app.workspace_api import role_refusal

KEY = "k" * 32


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "t.db")


def test_the_owner_is_owner_and_an_invite_joins_once_with_its_role(db):
    wid = m.workspace_of(db, "google:a")
    assert m.role_in(db, wid, "google:a") == "owner" and m.role_in(db, wid, "google:b") is None
    row, token = m.invite(db, KEY, wid, "B@Example.com", "reviewer", "google:a", 5)
    assert row["email"] == "b@example.com" and row["state"] == "waiting" and m.invites(db, wid)[0]["id"] == row["id"]
    joined = m.accept(db, KEY, token, "google:b", "b@example.com", "Bea")
    assert (joined.role, joined.spend_limit_usd) == ("reviewer", 5)
    assert m.role_in(db, wid, "google:b") == "reviewer" and m.invites(db, wid) == []
    with pytest.raises(m.LinkRefused, match="already been used"):
        m.accept(db, KEY, token, "google:c", None, None)
    assert [w["role"] for w in m.workspaces_for(db, "google:b")] == ["owner", "reviewer"]   # their own, then A's


def test_a_bent_turned_off_or_old_invite_is_refused(db, monkeypatch):
    wid = m.workspace_of(db, "google:a")
    row, token = m.invite(db, KEY, wid, "c@x.io", "editor", "google:a")
    with pytest.raises(m.LinkRefused, match="not valid"):
        m.resolve_invite(db, KEY, token[:-2] + "xx")
    with pytest.raises(m.LinkRefused, match="not valid"):
        m.resolve_invite(db, "other-key", token)
    _, newer = m.invite(db, KEY, wid, "c@x.io", "reviewer", "google:a")        # a new invite turns the older off
    with pytest.raises(m.LinkRefused, match="turned off"):
        m.resolve_invite(db, KEY, token)
    monkeypatch.setattr(m, "now_iso", lambda: "2099-01-01T00:00:00.000Z")   # 14 days are long gone
    with pytest.raises(m.LinkRefused, match="expired"):
        m.resolve_invite(db, KEY, newer)


def test_invites_check_their_input_and_the_owner_cannot_join_their_own(db):
    wid = m.workspace_of(db, "google:a")
    for bad in ("", "nope", "a@b", "@b.co"):
        with pytest.raises(m.MemberError, match="Enter an email"):
            m.invite(db, KEY, wid, bad, "editor", "google:a")
    with pytest.raises(m.MemberError, match="Editor or a Reviewer"):
        m.invite(db, KEY, wid, "x@y.z", "owner", "google:a")
    _, token = m.invite(db, KEY, wid, "a@y.z", "editor", "google:a")
    with pytest.raises(m.MemberError, match="your own workspace"):
        m.accept(db, KEY, token, "google:a", None, None)


def test_role_and_limit_changes_and_removal(db):
    wid = m.workspace_of(db, "google:a")
    _, token = m.invite(db, KEY, wid, "b@y.z", "editor", "google:a", 10)
    m.accept(db, KEY, token, "google:b", None, None)
    assert m.set_role(db, wid, "google:b", "reviewer").spend_limit_usd == 10
    assert m.set_role(db, wid, "google:b", clear_limit=True).spend_limit_usd is None
    with pytest.raises(m.MemberError):
        m.set_role(db, wid, "google:b", spend_limit_usd=-1)
    assert m.remove(db, wid, "google:b") and m.role_in(db, wid, "google:b") is None


def test_a_login_link_works_once_for_fifteen_minutes(db, monkeypatch):
    token = m.login_link(db, KEY, "Me@Example.com")
    assert m.use_login_link(db, KEY, token) == "me@example.com"
    with pytest.raises(m.LinkRefused, match="already been used"):
        m.use_login_link(db, KEY, token)
    old = m.login_link(db, KEY, "me@example.com")
    with db.tx() as c:                         # a changed expiry breaks the signature
        c.execute("UPDATE login_links SET expires_at = '2099-01-01T00:00:00.000Z' WHERE used_at IS NULL")
    with pytest.raises(m.LinkRefused, match="not valid"):
        m.use_login_link(db, KEY, old)
    later = m.login_link(db, KEY, "me@example.com")
    monkeypatch.setattr(m, "now_iso", lambda: "2099-01-01T00:00:00.000Z")
    with pytest.raises(m.LinkRefused, match="expired"):
        m.use_login_link(db, KEY, later)
    with pytest.raises(m.LinkRefused, match="not valid"):
        m.use_login_link(db, KEY, "l123.abc")


@pytest.mark.parametrize("role, method, path, ok", [
    ("owner", "DELETE", "/workspace/members/x", True),
    ("editor", "POST", "/projects", True),
    ("editor", "POST", "/videos/p1/turns", True),
    ("editor", "GET", "/workspace/members", False),
    ("editor", "POST", "/workspace/invites", False),
    ("editor", "GET", "/api/billing/plan", False),
    ("editor", "POST", "/workspace/switch", True),
    ("reviewer", "GET", "/projects/f1", True),
    ("reviewer", "GET", "/videos/p1/events", True),
    ("reviewer", "POST", "/videos/p1/comments", True),
    ("reviewer", "POST", "/videos/p1/comments/3/replies", True),
    ("reviewer", "POST", "/videos/p1/comments/3/resolve", False),
    ("reviewer", "POST", "/projects", False),
    ("reviewer", "PATCH", "/projects/f1", False),
    ("reviewer", "DELETE", "/videos/p1", False),
    ("reviewer", "POST", "/videos/p1/turns", False),
    ("reviewer", "PUT", "/me/notifications/settings", True),
    ("reviewer", "POST", "/invites/abc/accept", True),
])
def test_the_role_matrix(role, method, path, ok):
    assert (role_refusal(role, method, path) is None) is ok


def test_a_members_month_counts_against_their_limit(db):
    ledger = Ledger(db)
    wid = m.workspace_of(db, "google:a")
    with db.tx() as c:
        c.execute("INSERT INTO videos (id, owner, source, transcript, created_at, workspace_id) VALUES ('p1', 'google:a', '{}', '{}', '2026-10-01', ?)", (wid,))
    token = current_actor.set("google:b")
    try:
        ledger.record("p1", "anthropic", "turn", 100, "tokens", 0.30)
    finally:
        current_actor.reset(token)
    ledger.record("p1", "anthropic", "turn", 100, "tokens", 0.50)       # the owner's own, not B's
    assert ledger.spent_usd_by_actor("google:b", wid) == pytest.approx(0.30)
    ledger.ensure_can_spend("p1", member=("google:b", wid, 1.0))
    with pytest.raises(MemberLimitReached, match=r"reached your \$0\.25 spend limit in this workspace"):
        ledger.ensure_can_spend("p1", member=("google:b", wid, 0.25))


def test_migration_0024_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    cols = lambda: {r[1] for r in conn.execute("PRAGMA table_info(usage)")}
    assert {"workspace_members", "workspace_invites", "login_links"} <= tabs() and "by" in cols()
    migrate.down_to(conn, 23)   # back to 0023
    assert not ({"workspace_members", "workspace_invites", "login_links"} & tabs()) and "by" not in cols()
    assert "learned_items" in tabs()
    migrate.up(conn)
    assert {"workspace_members", "workspace_invites", "login_links"} <= tabs() and "by" in cols()
