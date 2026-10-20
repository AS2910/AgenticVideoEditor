"""F3: the project rules store. Four kinds, validated; every change bumps
the rule's version and the project's rules version; 0010 goes down and up."""
import os
import shutil

import pytest

from app.agent.context import brief_block, rules_lines
from app.store import migrate, rules
from app.store.db import Database
from app.store.repository import ProjectRepository


@pytest.fixture()
def repo():
    r = ProjectRepository(Database())
    r.create_project("local", "Spring")
    return r


def test_rules_are_added_changed_and_removed_with_versions(repo):
    db = repo.db
    word = rules.add(db, "f1", "pronounce", {"term": "Lumiere", "say": "loo-mee-air", "extra": "x"}, "local")
    assert (word.kind, word.data, word.version) == ("pronounce", {"term": "Lumiere", "say": "loo-mee-air"}, 1)
    banned = rules.add(db, "f1", "banned", {"word": "  cheap  "}, "local")
    assert banned.data == {"word": "cheap"}
    assert rules.rules_version(db, "f1") == 2
    changed = rules.update(db, "f1", word.rule_id, {"term": "Lumiere", "say": "loo-mee-yair", "respell": "LOO-mee-yair"}, "local")
    assert changed.version == 2 and changed.data["respell"] == "LOO-mee-yair"
    assert rules.update(db, "f1", word.rule_id, dict(changed.data), "local").version == 2   # the same again: no change
    assert rules.rules_version(db, "f1") == 3
    assert [r.kind for r in rules.list_rules(db, "f1")] == ["pronounce", "banned"]
    assert [r.rule_id for r in rules.list_rules(db, "f1", "banned")] == [banned.rule_id]
    assert rules.remove(db, "f1", banned.rule_id) and not rules.remove(db, "f1", banned.rule_id)
    assert rules.rules_version(db, "f1") == 4
    assert rules.update(db, "f1", 999, {"word": "x"}, "local") is None
    assert rules.get(db, "f2", word.rule_id) is None                     # another project's id finds nothing
    assert rules.add(db, "f9", "banned", {"word": "x"}, "local") is None


@pytest.mark.parametrize("kind,data,says", [
    ("shout", {"text": "x"}, "one of"), ("pronounce", {"term": "Lumiere"}, "needs say"),
    ("banned", {"word": "   "}, "needs word"), ("required_line", "T&C apply", "an object")])
def test_bad_rules_are_refused_with_a_sentence(repo, kind, data, says):
    with pytest.raises(rules.RuleError, match=says):
        rules.add(repo.db, "f1", kind, data, "local")


def test_the_opening_lines_are_plain_and_absent_when_there_are_none():
    assert rules_lines([]) == []
    lines = rules_lines([
        {"kind": "pronounce", "data": {"term": "Lumiere", "say": "loo-mee-air", "respell": "LOO-mee-air"}},
        {"kind": "pronounce", "data": {"term": "Ghee", "say": "gee"}},
        {"kind": "banned", "data": {"word": "cheap"}}, {"kind": "banned", "data": {"word": "free"}},
        {"kind": "required_line", "data": {"text": "T&C apply"}},
        {"kind": "style", "data": {"text": "Warm, never pushy"}}, {"kind": "style", "data": {"text": "Short lines."}},
    ])
    assert lines == [
        "Project words, say them this way: “Lumiere” as “loo-mee-air” (respelled “LOO-mee-air”); “Ghee” as “gee”.",
        "Never say these words: “cheap”, “free”.",
        "Every video in this project carries these lines: “T&C apply”.",
        "Project style rules: Warm, never pushy. Short lines.",
    ]
    assert not any("—" in line for line in lines)
    block = brief_block({"name": "Spring", "brief": "Bright.", "rules": [{"kind": "banned", "data": {"word": "cheap"}}]})
    assert block[-1] == "Never say these words: “cheap”."
    assert brief_block({"name": "Spring", "brief": "Bright."})[-1].startswith("Sister videos")


def test_0010_goes_down_and_up_leaving_projects_as_they_were():
    conn = migrate.connect(":memory:")
    migrate.up(conn, 9)
    conn.execute("INSERT INTO projects (id, owner, name, created_at) VALUES ('f1', 'local', 'A', 'x')")
    assert list(migrate.up(conn, 1)) == [10]
    assert conn.execute("SELECT rules_version FROM projects").fetchone()[0] == 0
    assert migrate.down(conn, 1) == [10]
    assert "project_rules" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "rules_version" not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
