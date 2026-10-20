"""A1: which videos were made with an older brief, and the free word-overlap
check that decides whether a brief change touches a video at all."""
import json

from app.store import briefs, migrate

AT = "2026-10-20T00:00:00.000Z"


def test_stale_only_when_something_shipped_with_an_older_brief():
    assert briefs.stale(1, 2) and briefs.stale(0, 1)
    assert not briefs.stale(2, 2)
    assert not briefs.stale(None, 3)          # nothing shipped: never stale
    assert not briefs.stale(1, None)          # standalone, or no brief


def test_changed_words_leave_out_the_common_ones_and_keep_numbers():
    runs = briefs.diff_text("Get 20% off. Always say the price first.", "Get 30% off. Always say the price first.")
    assert briefs.changed_words(runs) == {"20%", "20", "30%", "30"}


def test_a_change_touches_a_video_only_through_its_own_words():
    runs = briefs.diff_text("Offer: 20% off.", "Offer: 30% off.")
    assert briefs.touches(runs, ["Get 20% off today only."]) == ["20", "20%"]
    assert briefs.touches(runs, ["Welcome back to the show."]) == []
    assert briefs.touches(runs, ["Welcome back.", "Now 30% off."]) == ["30", "30%"]   # a shipped line counts
    assert briefs.touches([], ["Get 20% off."]) == []


def _at_0013(conn):
    migrate.up(conn, 13)
    conn.execute("INSERT INTO projects (id, owner, name, brief, created_at, workspace_id, brief_version) "
                 "VALUES ('f1', 'local', 'A', 'Price first.', ?, 'w1', 3)", (AT,))
    for vid, folder, settings in (("p1", "f1", {"last_turn": {"brief_version": 2}}), ("p2", "f1", {}),
                                  ("p3", "f1", {}), ("p4", None, {})):
        conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript, project_id, settings) "
                     "VALUES (?, 'local', ?, '{}', '{}', ?, ?)", (vid, AT, folder, json.dumps(settings)))
    for vid, body in (("p1", {"edit_id": "e1"}), ("p2", {"edit_id": "e1"}), ("p3", {"edit_id": "e1", "reverted": True}),
                      ("p4", {"edit_id": "e1"})):
        conn.execute("INSERT INTO edits (project_id, seq, body) VALUES (?, 1, ?)", (vid, json.dumps(body)))


def test_0014_backfills_what_each_shipped_video_was_made_with_and_down_drops_it():
    conn = migrate.connect(":memory:")
    _at_0013(conn)
    assert migrate.up(conn, 1) == {14: 2}
    got = dict(conn.execute("SELECT id, made_with_brief FROM videos").fetchall())
    # p1: the version its last turn read; p2: the project's current one; p3: only an undone edit; p4: standalone.
    assert got == {"p1": 2, "p2": 3, "p3": None, "p4": None}
    assert migrate.down(conn, 1) == [14]
    assert "made_with_brief" not in {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    assert migrate.up(conn, 1) == {14: 2}
