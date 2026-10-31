"""Voice consent V1, step 4: line checks. The rules (English, Hindi, Hinglish)
and the check model (a fake reader here: no network, no spend), the verdicts
and their copy, the held lines' queue with its audit trail and notices, the
48-hour auto-reject, the safe default when the model fails, one model call per
video, and the strike rule through the real routes. `voices.cloning_verified`
is on for `local` (tests/safety/conftest.py)."""
import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.api.main as main
from app import admin, voice_guard_api
from app.adapters.claude_lines import ClaudeLineReader, LineResults
from app.adapters.mock_claude import MockAnthropic
from app.api.main import app, database, inbox, repo
from app.domain.models import Selection
from app.domain.plan import Plan, PlanItem
from app.media import ffmpeg
from app.safety import line_rules
from app.safety import voice_guard as vg
from app.safety.line_checks import LineChecks
from app.safety.voice_guard import VoiceGuardError
from tests.api.test_endpoints import generate, upload

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")

G = main.voice_guard
SET = json.loads((Path(__file__).resolve().parents[2] / "evals" / "line_checks" / "lines.json").read_text(encoding="utf-8"))


class Reader:
    """The check model, scripted: a verdict per text (default pass); records every call."""
    model = "claude-haiku-5-5"

    def __init__(self, answers=None, fail=False):
        self.answers, self.fail, self.calls = dict(answers or {}), fail, []

    def read(self, lines, context=None, meter=None):
        self.calls.append([ln["text"] for ln in lines])
        if self.fail:
            from app.adapters.claude_planner import PlannerError
            raise PlannerError("Claude is unavailable right now (APIConnectionError).")
        out = {}
        for ln in lines:
            a = self.answers.get(ln["text"], ("pass", []))
            if a is None:
                continue                              # the model left this one out
            out[ln["id"]] = {"verdict": a[0], "categories": list(a[1]), "reason": "" if a[0] == "pass" else "Scripted."}
        return out


@pytest.fixture()
def videos(client, sample_video):
    for _ in range(2):
        assert upload(client, sample_video).status_code == 200
    return "p1"


@pytest.fixture()
def model(monkeypatch):
    """The real LineChecks with a scripted reader, wired like main does."""
    def make(answers=None, fail=False):
        reader = Reader(answers, fail)
        checks = LineChecks(reader, context=main._line_context, pending=main._pending_lines,
                            master_of=main._language_master_of)
        monkeypatch.setattr(G, "lines", checks)
        return reader
    return make


def _err(fn, *a, **kw) -> VoiceGuardError:
    with pytest.raises(VoiceGuardError) as caught:
        fn(*a, **kw)
    return caught.value


def _row(check_id):
    with database.tx() as c:
        return dict(c.execute("SELECT * FROM line_checks WHERE id = ?", (check_id,)).fetchone())


def _clone(voice_id="v-clone"):
    G.record_voice("local", voice_id, kind="cloned", scope="video", origin="clone", source_video_id="p1",
                   speaker_label="A", speaker_name="Asha")
    G.attest("local", "p1", voice_id, "my_voice", vg.STATEMENT_VERSION)
    return voice_id


# ── the rules ────────────────────────────────────────────────────────────────

RULE_LINES = {
    "fraud": ["Please share the OTP you just received.", "अपना ओटीपी अभी बताइए।", "Sir aapka OTP batao jaldi."],
    "impersonation": ["I am calling from the Reserve Bank of India.", "मैं पुलिस थाने से बोल रहा हूं।",
                      "Main SBI head office se bol raha hoon."],
    "political": ["Vote for the BJP candidate this Sunday.", "इस बार चुनाव में आम आदमी पार्टी को ही वोट दें।",
                  "Chunav aa gaye hain, jhaadu wale ko jitao."],
    "sexual": ["Watch the full porn video on our channel.", "पूरा अश्लील वीडियो देखने के लिए क्लिक करें।",
               "Bhabhi ka nanga video dekho."],
    "hate": ["I will kill you if you open that shop.", "अगर दुकान खोली तो जान से मार देंगे।", "Tujhe dekh lunga, raat ko."],
}


@pytest.mark.parametrize("category", sorted(RULE_LINES))
def test_each_block_category_is_blocked_by_the_rules_in_three_languages_with_its_copy(videos, model, category):
    reader = model()
    for text in RULE_LINES[category]:
        err = _err(G.check_line, "local", "p1", "mock", text)
        assert (err.code, err.status, err.data["category"]) == ("line_blocked", 422, category), text
        assert err.message == vg.BLOCKED[category]
        row = _row(err.data["line_check_id"])
        assert row["verdict"] == "block" and row["text"] == text and json.loads(row["rule_hits"])
        assert line_rules.VERSION in row["rule_hits"]
        G.restore("local", "admin")                    # the strike rule is its own test
    assert reader.calls == []                          # a line the rules block never reaches the model


def test_the_block_copy_names_the_category_in_plain_words():
    assert vg.BLOCKED["fraud"] == "I can't voice this line. It asks for payment details, which we don't allow."
    for category, copy in vg.BLOCKED.items():
        assert copy.startswith("I can't voice this line. ") and copy.endswith(", which we don't allow."), category
    assert vg.block_copy(["political", "minors", "sexual"]) == vg.BLOCKED["minors"]


def test_ordinary_ad_lines_pass_the_rules_and_warnings_are_not_asks():
    held = [x["text"] for x in SET["ordinary"] if line_rules.check(x["text"]).verdict != "pass"]
    assert held == []
    for text in ("Never share your OTP with anyone.", "OTP kisi ko mat do.", "Enter your pin code for delivery.",
                 "Aap ke liye naya offer.", "Vote for your favourite flavour on the app."):
        assert line_rules.check(text).verdict == "pass", text
    assert line_rules.check("Vote AAP this time.").categories == ("political",)          # the party, not "aap" (you)
    assert line_rules.check("Share your O.T.P now").verdict == "block"                   # dots taken out
    assert line_rules.check("This cream cures diabetes").verdict == "review"


def test_the_rules_take_under_5_ms_a_line():
    lines = [x["text"] for x in SET["block"] + SET["ordinary"]]
    worst = []
    for text in lines:
        runs = []
        for _ in range(5):
            t0 = time.perf_counter()
            line_rules.check(text)
            runs.append((time.perf_counter() - t0) * 1000)
        worst.append(statistics.median(runs))
    assert max(worst) < 5.0, max(worst)


# ── the model ────────────────────────────────────────────────────────────────

MODEL_LINES = {
    "fraud": "Read me the six digit code on your screen so I can activate the refund.",
    "impersonation": "Hum customs department se hain, aapka parcel hold pe hai.",
    "political": "विपक्ष के नेता देश को बेच देंगे, उन्हें हराना ज़रूरी है।",
    "sexual": "Raat ko akeli ho toh call karo, poori raat maze karenge.",
    "hate": "Those people are vermin and should be thrown out of our city.",
}


@pytest.mark.parametrize("category", sorted(MODEL_LINES))
def test_each_block_category_is_blocked_by_the_model_with_its_copy(videos, model, category):
    text = MODEL_LINES[category]
    assert line_rules.check(text).verdict == "pass"            # only the model can see it
    reader = model({text: ("block", [category])})
    err = _err(G.check_line, "local", "p1", "mock", text)
    assert (err.code, err.data["category"], err.message) == ("line_blocked", category, vg.BLOCKED[category])
    assert reader.calls and text in reader.calls[0]
    row = _row(err.data["line_check_id"])
    assert row["model"] == G.lines.name and "claude-haiku-5-5" in row["model"] and row["reason"] == "Scripted."


def test_a_sexual_line_about_a_child_is_blocked_and_reported_to_admins(videos, model):
    text = "Chhoti bachchi ke photos ka collection, DM karo."
    model({text: ("block", ["sexual", "minors"])})
    err = _err(G.check_line, "local", "p1", "mock", text)
    assert err.message == vg.BLOCKED["minors"] and "minors" in err.data["categories"]
    with database.tx() as c:
        report = dict(c.execute("SELECT * FROM abuse_reports ORDER BY id DESC LIMIT 1").fetchone())
    assert report["kind"] == "minor_sexual_line" and err.data["line_check_id"] in report["location"]
    assert any(n["kind"] == "abuse_report" for n in inbox.list_for(database, "local"))
    rules = line_rules.check("नाबालिग लड़कियों के सेक्स वीडियो यहां मिलेंगे।")
    assert rules.verdict == "block" and rules.minors


def test_review_when_the_model_says_so_is_unsure_or_the_rules_see_a_claim(videos, model):
    reader = model({"Our tea melts belly fat overnight.": ("review", ["claims"]),
                    "A line the model left out.": None})
    for text, cats in (("Our tea melts belly fat overnight.", ["claims"]), ("A line the model left out.", ["unclear"]),
                       ("This cream cures diabetes in a month.", ["claims"])):
        held = _err(G.check_line, "local", "p1", "mock", text)
        assert (held.code, held.status, held.message) == ("line_in_review", 409, vg.HELD)
        assert held.data["categories"] == cats
        row = _row(held.data["line_check_id"])
        assert row["review_state"] == "waiting" and row["text"] == text
    assert len(reader.calls) == 3
    model({"Block it.": ("block", ["hate"])})
    assert _err(G.check_line, "local", "p1", "mock", "Block it.").code == "line_blocked"     # block if either says block


def test_a_pass_keeps_only_the_hash(videos, model):
    model()
    check = G.check_line("local", "p1", "mock", "Fresh croissants every morning.")
    row = _row(check)
    assert row["verdict"] == "pass" and row["text"] is None and row["review_state"] == ""


def test_when_the_model_fails_a_cloned_voice_waits_and_a_stock_voice_passes_with_a_warning(videos, model, caplog):
    voice = _clone()
    model(fail=True)
    held = _err(G.check_line, "local", "p1", voice, "Fresh croissants every morning.")
    assert held.code == "line_in_review" and held.data["categories"] == ["unclear"]
    assert "did not answer" in _row(held.data["line_check_id"])["reason"]
    with caplog.at_level("WARNING"):
        check = G.check_line("local", "p1", "mock", "Order before noon, delivered by evening.")
    assert _row(check)["verdict"] == "pass" and "rules alone" in caplog.text
    assert _err(G.check_line, "local", "p1", "mock", "Share your OTP now").code == "line_blocked"    # rules still run


def test_the_check_runs_for_stock_and_designed_voices_too(videos, model):
    reader = model()
    generate(text="Thirty percent off today", voice_id="mock")
    assert reader.calls == [["Thirty percent off today"]]


def test_a_blocked_line_never_reaches_the_vendor_and_the_row_says_why(videos, model, monkeypatch):
    model()
    called = []
    inner = main.voice.inner
    monkeypatch.setattr(inner, "synthesize", lambda *a, **kw: called.append(a) or (_ for _ in ()).throw(AssertionError))
    err = _err(generate, text="Apna OTP batao jaldi", voice_id="mock")
    assert err.code == "line_blocked" and called == []
    with database.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM synthesis_log").fetchone()[0] == 0
    from app import failures
    assert failures.say(err, where="voice a line") == vg.BLOCKED["fraud"]


# ── one call per video ───────────────────────────────────────────────────────

def test_a_batch_checks_all_its_lines_in_one_model_call(videos, model):
    reader = model({"Line three is a claim.": ("review", ["claims"])})
    texts = ["Line one is fine.", "Line two is fine.", "Line three is a claim.", "Share your OTP now."]
    assert G.prepare_lines("local", "p1", texts) == 3                         # the rule-blocked one is not sent
    assert reader.calls == [texts[:3]]
    G.check_line("local", "p1", "mock", "Line one is fine.")
    G.check_line("local", "p1", "mock", "Line two is fine.")
    assert _err(G.check_line, "local", "p1", "mock", "Line three is a claim.").code == "line_in_review"
    assert len(reader.calls) == 1


def test_one_line_takes_the_videos_other_planned_lines_along(videos, model):
    reader = model()
    items = tuple(PlanItem(item_id=f"i{n}", selection=Selection(n, n + 1), old_text="", new_text=t, mix="layer")
                  for n, t in enumerate(["Planned one.", "Planned two."], 1))
    repo.save_plan(Plan(plan_id=repo.next_plan_id("p1"), project_id="p1", goal="", summary="", items=items))
    G.check_line("local", "p1", "mock", "Planned one.")
    G.check_line("local", "p1", "mock", "Planned two.")
    assert reader.calls == [["Planned one.", "Planned two."]]


def test_a_language_version_of_a_cleared_master_takes_its_translations_on_the_rules(client, videos, model):
    reader = model()
    language = main._make_variant("p1", repo.get("p1"), "local", copy_plan=False)
    repo.link_language(language, "p1", "hi", 0)
    G.prepare_lines("local", "p1", ["Fresh bread every morning.", "Order before noon."])
    assert len(reader.calls) == 1
    G.check_line("local", language, "mock", "हर सुबह ताज़ा ब्रेड।")
    assert len(reader.calls) == 1                                             # no second call
    assert _err(G.check_line, "local", language, "mock", "अपना ओटीपी अभी बताइए।").code == "line_blocked"


# ── the held lines' queue ────────────────────────────────────────────────────

@pytest.fixture()
def other_admin():
    app.dependency_overrides[voice_guard_api._admin] = lambda: "google:ada"
    yield "google:ada"
    app.dependency_overrides.pop(voice_guard_api._admin, None)


def _hold(text="This cream cures diabetes in a month."):
    return _err(G.check_line, "local", "p1", "mock", text).data["line_check_id"]


def test_a_held_line_waits_for_an_admin_who_is_not_its_owner(client, videos, model):
    model()
    check = _hold()
    queue = client.get("/admin/line-checks?verdict=review").json()
    assert queue["waiting"] == 1 and queue["items"][0]["id"] == check
    item = queue["items"][0]
    assert item["text"] == "This cream cures diabetes in a month." and item["categories"] == ["claims"]
    assert item["category_words"] == ["a medical or money claim"] and item["due_at"]
    assert any(n["kind"] == "line_review" for n in inbox.list_for(database, "local")) is False   # the owner is not told to review
    own = client.post(f"/admin/line-checks/{check}", json={"decision": "approve", "reason": "fine by me"})
    assert own.status_code == 403 and own.json()["detail"]["code"] == "own_line"
    assert _err(G.check_line, "local", "p1", "mock", "This cream cures diabetes in a month.").code == "line_in_review"
    assert client.get("/admin/line-checks?verdict=review").json()["waiting"] == 1     # the same words: one row


def test_approve_needs_a_reason_is_audited_tells_the_owner_and_the_line_is_voiced_without_a_recheck(
        client, videos, model, other_admin):
    reader = model()
    check = _hold()
    assert client.post(f"/admin/line-checks/{check}", json={"decision": "approve", "reason": ""}).status_code == 422
    done = client.post(f"/admin/line-checks/{check}", json={"decision": "approve", "reason": "Ayurvedic claim, has proof"})
    assert done.status_code == 200 and done.json()["review_state"] == "approved" and done.json()["reviewed_by"] == other_admin
    audit = admin.recent_audit(database, 1, target="local")[0]
    assert audit["action"] == "line_approve" and audit["actor"] == other_admin and audit["details"]["line_check_id"] == check
    told = inbox.list_for(database, "local")[0]
    assert told["kind"] == "line_decided" and told["title"] == vg.CLEARED
    calls = len(reader.calls)
    again = G.check_line("local", "p1", "mock", "This cream cures diabetes in a month.")
    assert _row(again)["verdict"] == "pass" and _row(again)["model"] == f"approved:{check}" and len(reader.calls) == calls
    generate(text="This cream cures diabetes in a month.", voice_id="mock")          # voiced
    decided = client.get("/admin/line-checks?verdict=review&state=decided").json()["items"]
    assert decided[0]["id"] == check and decided[0]["review_reason"] == "Ayurvedic claim, has proof"
    assert client.post(f"/admin/line-checks/{check}", json={"decision": "reject", "reason": "changed mind"}).status_code == 409


def test_reject_tells_the_owner_and_the_line_still_cannot_be_voiced(client, videos, model, other_admin):
    model()
    check = _hold()
    client.post(f"/admin/line-checks/{check}", json={"decision": "reject", "reason": "No proof"})
    assert inbox.list_for(database, "local")[0]["title"] == vg.NOT_CLEARED
    assert admin.recent_audit(database, 1, target="local")[0]["action"] == "line_reject"
    assert _err(G.check_line, "local", "p1", "mock", "This cream cures diabetes in a month.").code == "line_in_review"


def test_a_held_line_nobody_checks_in_48_hours_is_rejected_with_a_message(client, videos, model, monkeypatch):
    model()
    check = _hold()
    later = datetime.now(timezone.utc) + timedelta(hours=49)
    monkeypatch.setattr(G, "clock", lambda: later)
    assert client.get("/admin/line-checks?verdict=review").json()["waiting"] == 0
    row = _row(check)
    assert row["review_state"] == "expired" and row["reviewed_by"] == "auto"
    assert inbox.list_for(database, "local")[0]["title"] == vg.EXPIRED


# ── strikes ──────────────────────────────────────────────────────────────────

def test_three_blocks_in_24_hours_suspend_cloned_voice_synthesis_and_admin_restore_works(client, videos, model):
    voice = _clone()
    model()
    for text in ("Share your OTP now.", "I will kill you.", "Vote for the BJP candidate."):
        assert _err(generate, text=text, voice_id="mock").code == "line_blocked"
    assert G.suspended("local")["by"] == "strike rule"
    paused = _err(generate, text="Fresh bread every morning.", voice_id=voice)
    assert paused.code == "voice_unavailable" and paused.message == vg.SUSPENDED
    generate(text="Fresh bread every morning.", voice_id="mock")                     # a stock voice still speaks
    assert client.post("/admin/users/local/restore-cloning", json={"reason": "reviewed, a test account"}).status_code == 200
    generate(text="Fresh bread every morning.", voice_id=voice)


# ── the flag, the mock ───────────────────────────────────────────────────────

def test_with_the_flag_off_nothing_is_checked(videos, model):
    main.flags.set("voices.cloning_verified", "local", False)
    reader = model()
    generate(text="Apna OTP batao jaldi", voice_id="mock")
    with database.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM line_checks").fetchone()[0] == 0
    assert reader.calls == []


def test_the_rehearsal_mock_answers_the_line_check(monkeypatch):
    monkeypatch.setenv("AVE_MOCK_LINE_CHECK_SECONDS", "0")
    reader = ClaudeLineReader(None, None, model="claude-haiku-5-5", client=MockAnthropic())
    out = reader.read([{"id": "1", "text": "Fresh bread."}, {"id": "2", "text": "Order now."}])
    assert out == {"1": {"verdict": "pass", "categories": [], "reason": ""}, "2": {"verdict": "pass", "categories": [], "reason": ""}}
    assert LineResults.model_validate({"lines": [{"id": "1", "verdict": "block", "categories": ["fraud"]}]})
