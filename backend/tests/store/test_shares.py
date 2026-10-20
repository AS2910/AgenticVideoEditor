"""F6: share tokens. A link is the row's id and an HMAC over it; a forged,
retargeted, revoked or expired link is refused with a sentence; the server's
key is generated once and kept in the data dir."""
import os

import pytest

from app.store import events, shares
from app.store.db import Database
from app.store.repository import ProjectRepository

KEY = "test-key"


@pytest.fixture()
def db():
    r = ProjectRepository(Database())
    r.create_project("local", "Spring")
    return r.db


def make(db, **kw):
    args = {"owner": "local", "project_id": "f1", "scope": "project", "target": "f1"} | kw
    return shares.create(db, KEY, **args)


def test_a_link_opens_its_share_for_thirty_days_by_default(db):
    share, token = make(db, name="  Asha  at  the agency ")
    assert token.startswith(share.share_id + ".") and share.role == "viewer" and share.name == "Asha at the agency"
    assert shares.resolve(db, KEY, token) == share
    assert share.expires_at[:10] > share.created_at[:10]
    from datetime import datetime
    days = (datetime.fromisoformat(share.expires_at.replace("Z", "+00:00")) - datetime.fromisoformat(share.created_at.replace("Z", "+00:00"))).days
    assert days in (29, 30)
    assert shares.token_for(KEY, share) == token                         # Copy link again gives the same link
    assert [e["verb"] for e in events.for_project(db, "f1")["events"]] == ["share.created"]


@pytest.mark.parametrize("bad", ["", "nodot", "sh123.abc", "x" * 300])
def test_garbage_is_not_a_valid_link(db, bad):
    with pytest.raises(shares.ShareRefused) as refused:
        shares.resolve(db, KEY, bad)
    assert refused.value.code == "invalid" and "not valid" in refused.value.message


def test_a_forged_or_retargeted_link_is_refused(db):
    share, token = make(db)
    with pytest.raises(shares.ShareRefused):
        shares.resolve(db, "another-key", token)                         # signed with someone else's key
    with pytest.raises(shares.ShareRefused):
        shares.resolve(db, KEY, token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
    with db.tx() as c:                                                   # the row pointed elsewhere
        c.execute("UPDATE share_tokens SET target = 'f2' WHERE id = ?", (share.share_id,))
    with pytest.raises(shares.ShareRefused) as refused:
        shares.resolve(db, KEY, token)
    assert refused.value.code == "invalid"


def test_a_revoked_link_says_it_was_turned_off(db):
    share, token = make(db)
    gone = shares.revoke(db, share.share_id, "local")
    assert gone.revoked_at and gone.revoked_by == "local" and gone.state() == "revoked"
    assert shares.revoke(db, share.share_id, "local").revoked_at == gone.revoked_at      # once
    with pytest.raises(shares.ShareRefused) as refused:
        shares.resolve(db, KEY, token)
    assert refused.value.code == "revoked" and "turned off" in refused.value.message
    assert shares.revoke(db, "sh-none", "local") is None
    verbs = [e["verb"] for e in events.for_project(db, "f1")["events"]]
    assert verbs.count("share.revoked") == 1


def test_an_expired_link_says_it_expired(db, monkeypatch):
    share, token = make(db, days=1)
    monkeypatch.setattr(shares, "now_iso", lambda: "2999-01-01T00:00:00.000Z")
    with pytest.raises(shares.ShareRefused) as refused:
        shares.resolve(db, KEY, token)
    assert refused.value.code == "expired" and "expired" in refused.value.message
    assert share.state("2999-01-01T00:00:00.000Z") == "expired"


@pytest.mark.parametrize("kw, words", [({"scope": "folder"}, "shares one of"), ({"role": "admin"}, "role"),
                                       ({"days": 0}, "lasts"), ({"days": 400}, "lasts"), ({"target": ""}, "Say what")])
def test_a_link_that_cannot_be_made_says_why(db, kw, words):
    with pytest.raises(shares.ShareError, match=words):
        make(db, **kw)


def test_links_are_listed_newest_first_and_narrowed(db):
    a, _ = make(db)
    b, _ = make(db, scope="video", target="p1", role="reviewer")
    assert [s.share_id for s in shares.list_for(db, "local", "f1")] in ([b.share_id, a.share_id], [a.share_id, b.share_id])
    assert [s.share_id for s in shares.list_for(db, "local", scope="video")] == [b.share_id]
    assert shares.list_for(db, "someone-else") == []


def test_the_key_is_made_once_and_kept_private(tmp_path):
    assert shares.secret(tmp_path, "from-config") == "from-config"
    made = shares.secret(tmp_path)
    assert len(made) == 64 and shares.secret(tmp_path) == made
    assert oct(os.stat(tmp_path / shares.SECRET_FILE).st_mode & 0o777) == "0o600"
