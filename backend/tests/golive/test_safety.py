"""G6 pieces: the liveness prompt and the fake check, the public-figure list,
the fake watermark (read back from the file) and the signed C2PA-style
manifest, consent records expire after the retention period, the data
export holds only the owner's rows, migration 0029 up and down."""
import json
import random
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import dataexport
from app.media import ffmpeg
from app.purge import expire_consent
from app.safety import figures, liveness, provenance
from app.store import migrate
from app.store.db import Database
from app.timefmt import iso

ffmpeg_only = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


def test_the_prompt_is_a_sentence_with_a_fresh_code():
    a, b = liveness.prompt(random.Random(1)), liveness.prompt(random.Random(2))
    assert a != b and "My code is" in a and any(a.startswith(s) for s in liveness.SENTENCES)
    assert "—" not in a


def test_the_fake_liveness_passes_a_recording_and_fails_short_or_unreadable_ones(tmp_path):
    seconds = {"ok.webm": 3.2, "short.webm": 0.4}

    def seconds_of(p: Path) -> float:
        if p.name not in seconds:
            raise ValueError("unreadable")
        return seconds[p.name]
    check = liveness.FakeLiveness(seconds_of)
    assert check.verify(Path("ok.webm"), "x").passed and check.test_mode
    short = check.verify(Path("short.webm"), "x")
    assert not short.passed and "too short" in short.reason
    assert "could not be read" in check.verify(Path("bad.webm"), "x").reason


def test_public_figures_match_by_their_words_not_by_a_part():
    check = figures.ListCheck()
    assert check.match("Narendra  Modi") == "Narendra Modi"
    assert check.match("modi narendra (speech)") == "Narendra Modi"
    assert check.match("Shāh Rukh Khan") == "Shah Rukh Khan"
    assert check.match("Narendra") is None and check.match("Priya") is None and check.match("") is None
    assert "—" not in figures.REFUSAL


@ffmpeg_only
def test_the_watermark_reads_back_and_the_manifest_is_signed(tmp_path, sample_video):
    out = tmp_path / "ad.mp4"
    out.write_bytes(Path(sample_video).read_bytes())
    signer = provenance.FakeSigner(b"k")
    wm = provenance.FakeWatermarker()
    made = provenance.stamp(out, video_id="p1", owner="ana", watermarker=wm, signer=signer, source_sha="s" * 64)
    assert wm.read(out) == made["mark"]
    assert abs(ffmpeg.duration_of(out) - ffmpeg.duration_of(sample_video)) < 0.1          # streams copied, untouched
    signed = json.loads(provenance.manifest_path(out).read_text())
    assert signed["manifest"]["asset"]["sha256"] == made["sha256"] and signed["signature"]["test_mode"]
    labels = [a["label"] for a in signed["manifest"]["assertions"]]
    assert "c2pa.actions" in labels and "c2pa.ai_generated" in labels
    assert signer.verify(signed["manifest"], signed["signature"])
    signed["manifest"]["title"] = "changed"
    assert not signer.verify(signed["manifest"], signed["signature"])


def test_consent_records_expire_after_the_retention_period(tmp_path):
    db = Database(tmp_path / "t.db")
    now = datetime(2033, 1, 1, tzinfo=timezone.utc)
    with db.tx() as c:
        for item, years in (("old", 7.5), ("new", 6.5)):
            c.execute("INSERT INTO purged_items (kind, item_id, name, owner, purged_at, consent) VALUES ('video', ?, 'v', 'ana', ?, ?)",
                      (item, iso(now - timedelta(days=365.25 * years)), json.dumps({"granted_at": "x"})))
        assert expire_consent(c, 7, now) == ["video:old"]
        kept = {r[0]: r[1] for r in c.execute("SELECT item_id, consent FROM purged_items")}
    assert kept["old"] is None and kept["new"] is not None


def test_the_data_export_holds_only_the_owners_rows(tmp_path):
    db = Database(tmp_path / "t.db")
    with db.tx() as c:
        for vid, owner in (("p1", "ana"), ("p2", "bo")):
            c.execute("INSERT INTO videos (id, owner, created_at, source, transcript) VALUES (?, ?, 'x', '{}', '{}')", (vid, owner))
            c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES (?, 'openai', 't', 1, 'minutes', 0.1, 'x')", (vid,))
        c.execute("INSERT INTO feedback (owner, video_id, target, target_id, vote, at) VALUES ('ana', 'p1', 'take', 'c1', 'up', 'x')")
        c.execute("INSERT INTO meta (key, value) VALUES ('my_voices:ana', ?)", (json.dumps([{"voice_id": "v1", "name": "Mine"}]),))
    (tmp_path / "artifacts" / "p1").mkdir(parents=True)
    (tmp_path / "artifacts" / "p1" / ("a" * 64 + ".mp4")).write_bytes(b"x" * 10)
    made = dataexport.build(db, "ana", tmp_path / "artifacts", tmp_path / "out" / "ana.zip")
    with zipfile.ZipFile(tmp_path / "out" / "ana.zip") as z:
        videos = json.loads(z.read("videos.json"))
        usage = json.loads(z.read("usage.json"))
        media = json.loads(z.read("media.json"))
        assert [v["id"] for v in videos] == ["p1"] and [u["project_id"] for u in usage] == ["p1"]
        assert json.loads(z.read("my_voices.json"))[0]["name"] == "Mine"
        assert json.loads(z.read("feedback.json"))[0]["vote"] == "up"
        assert media == [{"store": "p1", "file": "a" * 64 + ".mp4", "bytes": 10, "path": "p1/" + "a" * 64 + ".mp4"}]
        assert "README.txt" in z.namelist()
    assert made["media"] == 1


def test_migration_0029_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    mine = {"liveness_attempts", "abuse_reports", "data_requests", "provenance_marks"}
    assert mine <= tabs()
    migrate.down_to(conn, 28)   # back to 0028
    assert not (mine & tabs()) and "invoices" in tabs()
    migrate.up(conn)
    assert mine <= tabs()
