"""Cost 1d: the same file is transcribed, looked at and read once per owner."""
from tests.api.test_endpoints import client, project, reset_state, upload  # noqa: F401
from tests.api.test_understanding import Looker


class Counting:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def transcribe(self, source):
        self.calls += 1
        return self.inner.transcribe(source)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_a_second_upload_of_the_same_file_reads_nothing_again(client, sample_video, monkeypatch):
    import app.api.main as main
    heard, looker = Counting(main.transcriber), Looker()
    monkeypatch.setattr(main, "transcriber", heard)
    monkeypatch.setattr(main, "planner", looker)
    first = upload(client, sample_video).json()
    client.post(f"/videos/{first['video_id']}/reading", json={})
    second = upload(client, sample_video).json()
    reading = client.post(f"/videos/{second['video_id']}/reading", json={}).json()
    assert heard.calls == 1 and len(looker.calls) == 1
    assert second["transcript"] == first["transcript"] and reading["opening"] == "The knockdown comes at 0:01."
    assert client.get(f"/videos/{second['video_id']}/understanding").json()["read"]["genre"] == "boxing bout"
    # Asked to read it again, it reads again.
    client.post(f"/videos/{second['video_id']}/reading", json={"again": True})
    assert len(looker.calls) == 2


def test_a_changed_brief_reads_again_and_a_deleted_video_takes_its_reads(client, sample_video, monkeypatch):
    import app.api.main as main
    from app.store import content_cache
    looker = Looker()
    monkeypatch.setattr(main, "planner", looker)
    first = upload(client, sample_video).json()
    client.post(f"/videos/{first['video_id']}/reading", json={})
    monkeypatch.setattr(main, "_brief_text", lambda pid: "A boxing promo for Friday night.")
    second = upload(client, sample_video).json()
    client.post(f"/videos/{second['video_id']}/reading", json={})
    assert len(looker.calls) == 2
    sha = main.repo.get(first["video_id"]).source.media.sha256
    owner = main.repo.get(first["video_id"]).owner
    assert content_cache.get(main.database, owner, sha, "transcript", content_cache.key_of(main.transcriber_label, content_cache.VERSION))
    main._delete_project(first["video_id"])
    assert content_cache.get(main.database, owner, sha, "transcript", content_cache.key_of(main.transcriber_label, content_cache.VERSION)) is None


def test_the_migration_goes_up_and_down():
    import sqlite3
    from app.store.migrations import m0038_content_cache as m38
    from app.store.migrations._util import tables
    conn = sqlite3.connect(":memory:")
    m38.up(conn)
    assert "content_cache" in tables(conn)
    m38.down(conn)
    assert "content_cache" not in tables(conn)


def test_a_read_made_the_old_way_is_not_served(client, sample_video, monkeypatch):
    """Run 5 addendum 0a: a transcript kept before how clips are heard changed
    (run 5 item 4's voice activity detection) is not handed to a re-upload."""
    import app.api.main as main
    from app.store import content_cache
    heard = Counting(main.transcriber)
    monkeypatch.setattr(main, "transcriber", heard)
    first = upload(client, sample_video).json()
    sha = main.repo.get(first["video_id"]).source.media.sha256
    owner = main.repo.get(first["video_id"]).owner
    old = content_cache.key_of(main.transcriber_label)            # the key before VERSION
    content_cache.put(main.database, owner, sha, "transcript", old, {"words": [], "statements": []})
    monkeypatch.setattr(content_cache, "VERSION", "next")
    upload(client, sample_video)
    assert heard.calls == 2
