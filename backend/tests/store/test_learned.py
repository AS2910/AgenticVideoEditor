"""D2 in the store: the pass is due at 10, 20, 30 and only then; decisions
count per project; a newer suggestion replaces one still waiting; accept,
dismiss and remove change the brief and rules only as they say; the
request the pass reads; migration 0023 up and down."""
import pytest

from app.adapters.claude_style import SYSTEM
from app.store import briefs, learned, migrate, rules
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT


@pytest.fixture()
def repo(tmp_path):
    repo = ProjectRepository(Database(tmp_path / "ave.db"))
    repo.create_project("local", "Spring", "Bright and short.")
    repo.create(make_source(project_id="p1", filename="ad.mp4"), TRANSCRIPT, folder_id="f1")
    repo.create(make_source(project_id="p2", filename="alone.mp4"), TRANSCRIPT)
    return repo


def test_a_pass_is_due_at_every_tenth_decision_only():
    assert [n for n in range(0, 35) if learned.due(n)] == [10, 20, 30]


def test_decisions_count_per_project_and_a_standalone_video_counts_none(repo):
    with repo.db.tx() as c:
        for _ in range(3):
            _, n = learned.record_in(c, video_id="p1", decision="added", proposed_text="Hi", by="local")
        _, alone = learned.record_in(c, video_id="p2", decision="rejected", proposed_text="Hi", by="local")
    assert n == 3 and alone == 0 and learned.count(repo.db, "f1") == 3
    with pytest.raises(learned.LearnedError), repo.db.tx() as c:
        learned.record_in(c, video_id="p1", decision="shrugged", proposed_text="Hi", by="local")


def test_a_newer_suggestion_replaces_one_still_waiting(repo):
    a = learned.suggest(repo.db, "f1", "rule", "Short lines.", "x", 10)
    b = learned.suggest(repo.db, "f1", "brief", "Say the store name.", "y", 20)
    assert learned.pending(repo.db, "f1")["item_id"] == b["item_id"]
    with pytest.raises(learned.LearnedError):
        learned.accept(repo.db, "f1", a["item_id"], "local")
    with pytest.raises(learned.LearnedError):
        learned.suggest(repo.db, "f1", "voice", "x", "y", 30)


def test_accept_then_remove_puts_the_brief_and_rules_back(repo):
    v1 = briefs.current(repo.db, "f1").version
    line = learned.suggest(repo.db, "f1", "brief", "Say the store name.", "", 10)
    learned.accept(repo.db, "f1", line["item_id"], "local")
    assert briefs.current(repo.db, "f1").text == "Bright and short.\nSay the store name."
    rule = learned.suggest(repo.db, "f1", "rule", "Short lines.", "", 20)
    rule = learned.accept(repo.db, "f1", rule["item_id"], "local")
    assert [r.data for r in rules.list_rules(repo.db, "f1")] == [{"text": "Short lines."}]
    assert [i["text"] for i in learned.learned(repo.db, "f1")] == ["Say the store name.", "Short lines."]
    learned.remove(repo.db, "f1", line["item_id"], "local")
    learned.remove(repo.db, "f1", rule["item_id"], "local")
    now = briefs.current(repo.db, "f1")
    assert now.text == "Bright and short." and now.version == v1 + 2 and rules.list_rules(repo.db, "f1") == []
    assert learned.learned(repo.db, "f1") == []
    with pytest.raises(learned.LearnedError):
        learned.remove(repo.db, "f1", line["item_id"], "local")


def test_removing_a_line_the_user_already_took_out_makes_no_new_version(repo):
    item = learned.accept(repo.db, "f1", learned.suggest(repo.db, "f1", "brief", "Say it.", "", 10)["item_id"], "local")
    briefs.save(repo.db, "f1", "Something else entirely.", "local")
    v = briefs.current(repo.db, "f1").version
    learned.remove(repo.db, "f1", item["item_id"], "local")
    assert briefs.current(repo.db, "f1").version == v


def test_dismiss_changes_nothing_but_the_suggestion(repo):
    item = learned.suggest(repo.db, "f1", "rule", "Short lines.", "", 10)
    v = rules.rules_version(repo.db, "f1")
    learned.dismiss(repo.db, "f1", item["item_id"], "local")
    assert rules.rules_version(repo.db, "f1") == v and learned.pending(repo.db, "f1") is None


def test_the_request_reads_brief_rules_and_each_decision_plainly():
    text = learned.request_text({"name": "Spring", "brief": "Bright."}, [
        {"decision": "edited", "proposed_text": "Get 30% off", "final_text": "30% off", "reason": None},
        {"decision": "rejected", "proposed_text": "Buy now", "final_text": None, "reason": "Too pushy"},
    ], ["banned: cheap"])
    assert "Brief: Bright." in text and "Rules: banned: cheap" in text
    assert text.index('Thrown out: "Buy now". Why: Too pushy') < text.index('Rewritten, then added: "Get 30% off" became "30% off"')
    assert "—" not in SYSTEM


def test_migration_0023_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"proposal_decisions", "learned_items"} <= tabs()
    migrate.down_to(conn, 22)   # back to 0022
    assert not ({"proposal_decisions", "learned_items"} & tabs()) and "project_templates" in tabs()
    migrate.up(conn)
    assert {"proposal_decisions", "learned_items"} <= tabs()
