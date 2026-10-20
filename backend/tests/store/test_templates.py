"""D1 in the store: what a template keeps of a project (a word's clip stays
behind; a project never opened carries the three default presets), what a
project made from one gets, the starters' plain copy, and migration 0022
(project_templates) up and down."""
import re

import pytest

from app.store import migrate, presets, rules, templates
from app.store.db import Database
from app.store.repository import ProjectRepository


@pytest.fixture()
def repo(tmp_path):
    repo = ProjectRepository(Database(tmp_path / "ave.db"))
    repo.create_project("local", "Spring", "Bright and short.", settings={"autonomy": "draft"}, ceiling_usd=12.0)
    return repo


def test_a_snapshot_keeps_brief_rules_presets_defaults_and_ceiling_but_not_a_words_clip(repo):
    rules.add(repo.db, "f1", "pronounce", {"term": "Bhaji", "say": "BAH-jee", "audio": "a" * 64}, "local")
    rules.add(repo.db, "f1", "required_line", {"text": "T&C apply."}, "local")
    with repo.db.tx() as c:
        data = templates.snapshot_in(c, "f1", "local")
    assert data["brief"] == "Bright and short."
    assert data["rules"] == [{"kind": "pronounce", "data": {"term": "Bhaji", "say": "BAH-jee"}},
                             {"kind": "required_line", "data": {"text": "T&C apply."}}]
    # Never opened: the presets the page would show.
    assert [p["name"] for p in data["presets"]] == ["YouTube 16:9", "Reels 9:16", "Feed 1:1"]
    assert data["settings"] == {"autonomy": "draft"} and data["ceiling_usd"] == 12.0
    # Opened and emptied: none.
    for p in presets.list_presets(repo.db, "f1", "local"):
        presets.remove(repo.db, "f1", p.preset_id, "local")
    with repo.db.tx() as c:
        assert templates.snapshot_in(c, "f1", "local")["presets"] == []
        assert templates.snapshot_in(c, "nope", "local") is None


def test_apply_gives_rules_and_exactly_the_templates_presets(repo):
    made = repo.create_project("local", "Holi")
    data = templates.starter("starter-festive-ad").data
    with repo.db.tx() as c:
        templates.apply_in(c, made.project_id, {**data, "rules": [*data["rules"], {"kind": "nonsense", "data": {}}]}, "local")
    assert [r.kind for r in rules.list_rules(repo.db, made.project_id)] == ["required_line", "banned", "style"]
    # The defaults are not added on top: the template's presets are the project's.
    assert [p.name for p in presets.list_presets(repo.db, made.project_id, "local")] == ["Reels 9:16", "Feed 1:1", "YouTube 16:9"]


def test_starters_are_plain_have_rules_presets_and_defaults_and_cannot_change(repo):
    assert [t.name for t in templates.STARTERS] == ["Festive ad", "Product explainer", "Interview cleanup"]
    for t in templates.STARTERS:
        text = repr(t.to_dict())
        assert not re.search("[–—]", text), t.name
        assert t.data["brief"] and t.data["rules"] and t.data["presets"] and t.data["settings"] and t.data["ceiling_usd"]
        for r in t.data["rules"]:
            rules.clean(r["kind"], r["data"])
        for p in t.data["presets"]:
            presets.clean(p)
    assert any(r["data"].get("text") == "T&C apply." for r in templates.starter("starter-festive-ad").data["rules"])
    with pytest.raises(templates.TemplateError):
        templates.remove(repo.db, "local", "starter-festive-ad")
    with pytest.raises(templates.TemplateError):
        templates.rename(repo.db, "local", "starter-product-explainer", "Mine")


def test_own_templates_are_per_owner_newest_first_after_the_starters(repo):
    a = templates.save(repo.db, "local", "First", {"brief": "x"}, "f1")
    b = templates.save(repo.db, "local", "Second", {"brief": "y"}, "f1")
    templates.save(repo.db, "someone", "Theirs", {}, None)
    ids = [t.template_id for t in templates.list_for(repo.db, "local")]
    assert ids[:3] == [t.template_id for t in templates.STARTERS] and ids[3:] == [b.template_id, a.template_id]
    assert templates.get(repo.db, "someone", a.template_id) is None
    with pytest.raises(templates.TemplateError):
        templates.save(repo.db, "local", "   ", {})
    assert templates.rename(repo.db, "local", a.template_id, "Renamed").name == "Renamed"
    assert templates.remove(repo.db, "local", a.template_id) and not templates.remove(repo.db, "local", a.template_id)


def test_migration_0022_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "project_templates" in tabs()
    migrate.down(conn, max(migrate.applied(conn)) - 21)   # back to 0021
    assert "project_templates" not in tabs() and "pins" in tabs()
    migrate.up(conn)
    assert "project_templates" in tabs()
