"""B3: export presets and the file names their patterns make."""
import pytest

from app.store import presets
from app.store.db import Database
from app.store.repository import ProjectRepository


@pytest.fixture()
def db():
    r = ProjectRepository(Database())
    r.create_project("local", "Spring")
    return r.db


def test_file_names_follow_the_pattern_and_are_safe_on_any_disk():
    name = presets.file_name(presets.DEFAULT_PATTERN, project="Diwali Sale!", video="bhaji cam (final).MOV",
                             lang="en", preset="Reels 9:16", version=3)
    assert name == "Diwali-Sale_bhaji-cam-final_en_Reels-9-16_v3.mp4"
    assert presets.file_name("{video}", project="", video="ad.mp4", lang="", preset="", version=1) == "ad.mp4"
    # An empty token leaves no doubled separator behind.
    assert presets.file_name("{project}_{video}_{lang}_v{version}", project="P", video="a.mp4", lang="", preset="", version=2) == "P_a_v2.mp4"
    assert presets.file_name("../{video}/x", project="", video="a.mp4", lang="", preset="", version=1) == "a-x.mp4"
    assert len(presets.file_name("{video}", project="", video="x" * 400 + ".mp4", lang="", preset="", version=1)) <= presets.MAX_FILE


def test_defaults_are_written_once(db):
    first = presets.list_presets(db, "f1", "local")
    assert [p.name for p in first] == ["YouTube 16:9", "Reels 9:16", "Feed 1:1"]
    assert [p.name for p in presets.list_presets(db, "f1", "local")] == [p.name for p in first]
    for p in first:
        presets.remove(db, "f1", p.preset_id, "local")
    assert presets.list_presets(db, "f1", "local") == []
    assert presets.list_presets(db, "f9", "local") == []                  # no such project: nothing written


def test_hevc_is_refused_where_this_server_cannot_write_it(db):
    with pytest.raises(presets.PresetError, match="cannot write HEVC"):
        presets.add(db, "f1", {"name": "x", "platform": "feed", "codec": "hevc"}, "local", codecs=["h264"])
    made = presets.add(db, "f1", {"name": "x", "platform": "feed", "codec": "hevc"}, "local", codecs=["h264", "hevc"])
    assert made.codec == "hevc" and presets.update(db, "f1", made.preset_id, {"name": "x"}, "local") == made
