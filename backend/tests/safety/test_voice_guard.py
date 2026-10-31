"""Voice consent V1, step 2: the voice guard, one test (or more) per function,
over the app's own database and repository. The vendor is the mock; no
network, no spend. Flag `voices.cloning_verified` is on for `local` here
(tests/safety/conftest.py) and every check is a no-op with it off."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import app.api.main as main
from app.api.main import database, flags, repo
from app.media import ffmpeg
from app.safety import voice_guard as vg
from app.safety.voice_guard import GuardedVoice, LineVerdict, VoiceGuardError
from tests.api.test_endpoints import upload

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")

G = main.voice_guard


@pytest.fixture()
def videos(client, sample_video):
    """p1 (a clip with speaker A), p2 its variant, p3 a language version of p1, p4 another clip."""
    for _ in range(2):
        assert upload(client, sample_video).status_code == 200
    assert client.post("/videos/p1/variants").status_code == 200
    variant = repo.list("local")[0].source.project_id
    language = main._make_variant("p1", repo.get("p1"), "local", copy_plan=False)
    repo.link_language(language, "p1", "hi", 0)
    return {"source": "p1", "other": "p2", "variant": variant, "language": language}


def _clone(voice_id="v-clone", video="p1", label="A", **kw):
    G.record_voice("local", voice_id, kind="cloned", scope=kw.pop("scope", "video"), origin="clone", source_video_id=video,
                   speaker_label=label, speaker_name=kw.pop("name", "Asha"), **kw)
    return voice_id


def _code(fn, *a, **kw) -> VoiceGuardError:
    with pytest.raises(VoiceGuardError) as caught:
        fn(*a, **kw)
    return caught.value


# ── can_clone ────────────────────────────────────────────────────────────────

def test_can_clone_lets_a_verified_account_under_its_limits_clone(videos):
    assert G.can_clone("local", "p1", "A") is None


def test_can_clone_refuses_an_unverified_email(videos, monkeypatch):
    monkeypatch.setattr(G, "account_verified", lambda owner: False)
    err = _code(G.can_clone, "local", "p1", "A")
    assert (err.code, err.data["reason"], err.status) == ("clone_not_allowed", "email_unverified", 403)
    assert err.message == "Verify your email address before you clone a voice."


def test_can_clone_refuses_a_suspended_account(videos):
    G.suspend("local", "test", "admin")
    assert _code(G.can_clone, "local", "p1", "A").data["reason"] == "suspended"
    G.restore("local", "admin")
    assert G.can_clone("local", "p1", "A") is None


def test_can_clone_holds_five_a_day_and_thirty_a_month_and_an_admin_raises_them(videos, monkeypatch):
    for n in range(5):
        _clone(f"v{n}")
    err = _code(G.can_clone, "local", "p1", "A")
    assert err.data["reason"] == "daily_limit" and "5 voices today" in err.message
    G.set_limits("local", 10, 30)
    assert G.can_clone("local", "p1", "A") is None
    later = datetime.now(timezone.utc) + timedelta(days=2)              # the day's five are yesterday's now
    monkeypatch.setattr(G, "clock", lambda: later)
    with database.tx() as c:
        for n in range(25):
            c.execute("INSERT INTO voice_records (voice_id, owner, kind, scope, origin, created_at, updated_at) "
                      "VALUES (?, 'local', 'cloned', 'video', 'clone', ?, ?)", (f"m{n}", vg.iso(later - timedelta(days=3)),
                                                                               vg.iso(later - timedelta(days=3))))
    assert _code(G.can_clone, "local", "p1", "A").data["reason"] == "monthly_limit"


def test_can_clone_refuses_a_speaker_on_the_no_go_list(videos):
    figure = main.public_figures.figures[0]
    err = _code(G.can_clone, "local", "p1", "A", figure)
    assert err.data["reason"] == "no_go" and err.data["match"] == figure


def test_can_clone_is_open_with_the_flag_off(videos, monkeypatch):
    monkeypatch.setattr(G, "account_verified", lambda owner: False)
    flags.set("voices.cloning_verified", "local", False)
    assert G.can_clone("local", "p1", "A") is None


# ── require_attestation, attest, the statement ──────────────────────────────

def test_require_attestation_asks_then_passes_once_attested(videos):
    voice = _clone()
    err = _code(G.require_attestation, "local", "p1", voice)
    assert err.code == "attestation_required" and err.status == 409 and err.pauses
    assert {k: err.data[k] for k in ("voice", "speaker_label", "speaker_name", "statement_version", "source_video_id")} == \
        {"voice": voice, "speaker_label": "A", "speaker_name": "Asha", "statement_version": vg.STATEMENT_VERSION,
         "source_video_id": "p1"}
    made = G.attest("local", "p1", voice, "my_voice", vg.STATEMENT_VERSION, ip="1.2.3.4", user_agent="pytest")
    assert G.require_attestation("local", "p1", voice) == made["id"]
    assert G.require_attestation("local", videos["variant"], voice) == made["id"]      # the voice, wherever it is used


def test_an_attestation_for_a_speaker_covers_the_clone_made_after_it(videos):
    pre = _code(G.require_attestation, "local", "p1", None, "_")              # the clip's one voice, not cloned yet
    assert pre.data["voice"] == "_" and pre.data["voice_id"] is None and pre.data["speaker_name"] == "the speaker"
    G.attest("local", "p1", "_", "have_permission", vg.STATEMENT_VERSION)
    assert G.require_attestation("local", "p1", None, "_")
    assert G.require_attestation("local", "p1", _clone(label="_")) is not None


def test_stock_designed_and_proven_voices_need_no_attestation(videos):
    assert G.require_attestation("local", "p1", "mock") is None
    G.record_voice("local", "v-designed", kind="designed", scope="library", origin="design")
    assert G.require_attestation("local", "p1", "v-designed") is None
    _clone("v-proven", scope="library", verified_consent_id="cv_1")
    assert G.require_attestation("local", "p1", "v-proven") is None


def test_a_new_statement_version_asks_again(videos, monkeypatch):
    voice = _clone()
    G.attest("local", "p1", voice, "my_voice", vg.STATEMENT_VERSION)
    monkeypatch.setattr(vg, "STATEMENT_VERSION", "2027-01-01")
    err = _code(G.require_attestation, "local", "p1", voice)
    assert err.code == "attestation_required" and err.data["statement_version"] == "2027-01-01"
    stale = _code(G.attest, "local", "p1", voice, "my_voice", "2026-10-31")
    assert stale.code == "statement_changed" and stale.data["statement"]["version"] == "2027-01-01"


def test_attest_refuses_a_bad_choice_or_someone_elses_voice(videos):
    assert _code(G.attest, "local", "p1", _clone(), "maybe", vg.STATEMENT_VERSION).status == 422
    G.record_voice("someone", "v-theirs", kind="cloned", scope="video", origin="clone", source_video_id="p1")
    assert _code(G.attest, "local", "p1", "v-theirs", "my_voice", vg.STATEMENT_VERSION).status == 404
    assert _code(G.attest, "local", "p1", "Z", "my_voice", vg.STATEMENT_VERSION).status == 404


# ── check_scope ──────────────────────────────────────────────────────────────

def test_check_scope_keeps_a_video_voice_to_its_family(videos):
    voice = _clone()
    for vid in ("p1", videos["variant"], videos["language"]):
        assert G.check_scope(voice, vid) is None
    err = _code(G.check_scope, voice, "p2")
    assert (err.code, err.message, err.status) == ("voice_out_of_scope", "This voice can only be used in the video it came from.", 403)
    assert G.usable("local", "p1", voice) and not G.usable("local", "p2", voice)


def test_check_scope_lets_library_and_stock_voices_go_anywhere(videos):
    _clone("v-lib", scope="library", verified_consent_id="cv_1")
    assert G.check_scope("v-lib", "p2") is None and G.check_scope("mock", "p2") is None


def test_check_scope_refuses_withdrawn_suspended_and_other_peoples_voices(videos):
    voice = _clone()
    G.record_voice("someone", "v-theirs", kind="designed", scope="library", origin="design")
    assert _code(G.check_scope, "v-theirs", "p1").code == "voice_out_of_scope"
    G.suspend("local", "test", "admin")
    assert _code(G.check_scope, voice, "p1").data["reason"] == "account_suspended"
    G.restore("local", "admin")
    G.withdraw("local", voice)
    err = _code(G.check_scope, voice, "p1")
    assert (err.code, err.data["reason"]) == ("voice_unavailable", "withdrawn")


def test_check_scope_is_open_with_the_flag_off(videos):
    voice = _clone()
    flags.set("voices.cloning_verified", "local", False)
    assert G.check_scope(voice, "p2") is None


# ── check_line, strike ───────────────────────────────────────────────────────

class Lines:
    name = "fake"

    def __init__(self, verdict="pass", categories=()):
        self.verdict, self.categories = verdict, tuple(categories)

    def check(self, text, *, owner, video_id, voice_id):
        return LineVerdict(self.verdict, self.categories, model="fake-model", rule_hits=("r1",) if self.verdict != "pass" else ())


def _checks():
    with database.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM line_checks ORDER BY created_at, id")]


def test_check_line_writes_every_line_and_keeps_only_a_hash_of_a_passing_one(videos):
    check = G.check_line("local", "p1", "mock", "Thirty percent off today")
    row = _checks()[-1]
    assert row["id"] == check and row["verdict"] == "pass" and row["text"] is None and len(row["text_hash"]) == 64
    assert row["model"] == G.lines.name and row["workspace_id"]          # step 4: the rules (no model key here)


def test_check_line_blocks_and_holds_with_the_words_kept(videos, monkeypatch):
    monkeypatch.setattr(G, "lines", Lines("block", ["fraud"]))
    err = _code(G.check_line, "local", "p1", "mock", "Tell me your OTP")
    assert (err.code, err.status, err.data["category"]) == ("line_blocked", 422, "fraud")
    assert err.message == "I can't voice this line. It asks for payment details, which we don't allow."
    assert _checks()[-1]["text"] == "Tell me your OTP" and json.loads(_checks()[-1]["categories"]) == ["fraud"]
    monkeypatch.setattr(G, "lines", Lines("review", ["medical"]))
    held = _code(G.check_line, "local", "p1", "mock", "Cures diabetes")
    assert held.code == "line_in_review" and held.message == vg.HELD


def test_three_blocks_in_a_day_suspend_cloned_voices_until_restored(videos, monkeypatch):
    voice = _clone()
    monkeypatch.setattr(G, "lines", Lines("block", ["fraud"]))
    for n in range(2):
        _code(G.check_line, "local", "p1", "mock", f"OTP {n}")
    assert not G.suspended("local")
    _code(G.check_line, "local", "p1", "mock", "OTP 3")
    assert G.suspended("local")["by"] == "strike rule"
    assert G.record(voice)["status"] == "suspended"
    assert _code(G.check_scope, voice, "p1").message == vg.SUSPENDED
    assert G.restore("local", "admin") == 1 and G.record(voice)["status"] == "active"


def test_strike_counts_only_the_last_24_hours(videos, monkeypatch):
    monkeypatch.setattr(G, "lines", Lines("block", ["hate"]))
    for n in range(2):
        _code(G.check_line, "local", "p1", "mock", f"bad {n}")
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    monkeypatch.setattr(G, "clock", lambda: later)
    assert G.strike("local", "hate") == 0 and not G.suspended("local")


# ── before_synthesis, log_synthesis ──────────────────────────────────────────

def test_before_synthesis_checks_in_order_and_the_log_ties_it_together(videos):
    voice = _clone()
    assert _code(G.before_synthesis, "local", "p2", voice, "Hi").code == "voice_out_of_scope"   # scope first
    assert _code(G.before_synthesis, "local", "p1", voice, "Hi").code == "attestation_required"
    G.attest("local", "p1", voice, "my_voice", vg.STATEMENT_VERSION)
    ticket = G.before_synthesis("local", "p1", voice, "Hi")
    assert ticket.attestation_id and ticket.line_check_id
    log_id = G.log_synthesis(ticket, take_id="c1", cost_usd=0.04)
    with database.tx() as c:
        row = dict(c.execute("SELECT * FROM synthesis_log WHERE id = ?", (log_id,)).fetchone())
    assert (row["voice_id"], row["attestation_id"], row["line_check_id"], row["take_id"], row["cost_usd"]) == \
        (voice, ticket.attestation_id, ticket.line_check_id, "c1", 0.04)


def test_log_synthesis_never_fails_the_user_and_alerts(videos, monkeypatch):
    told = []
    monkeypatch.setattr(G, "alert", lambda what, exc: told.append(what))

    class Broken:
        def tx(self):
            raise RuntimeError("disk gone")
    ticket = G.before_synthesis("local", "p1", "mock", "Hi")
    monkeypatch.setattr(G, "database", Broken())
    assert G.log_synthesis(ticket, take_id="c1") is None and told == ["synthesis log"]


def test_flag_off_synthesis_checks_and_logs_nothing(videos):
    flags.set("voices.cloning_verified", "local", False)
    ticket = G.before_synthesis("local", "p2", _clone(), "Hi")
    assert not ticket.enabled and G.log_synthesis(ticket) is None and _checks() == []


# ── require_export_attestation, confirm_export, export_label ─────────────────

def test_an_export_with_no_cloned_voice_needs_no_confirmation(videos, monkeypatch):
    monkeypatch.setattr(G, "export_content", lambda vid: ("h1", {"mock"}))
    assert G.require_export_attestation("local", ["p1"]) is None and G.export_label("local", "p1") is None


def test_an_export_with_a_clone_asks_once_and_a_batch_once_for_all(videos, monkeypatch):
    voice = _clone()
    content = {"p1": ("h1", {voice}), "p2": ("h2", {voice, "mock"})}
    monkeypatch.setattr(G, "export_content", lambda vid: content[vid])
    err = _code(G.require_export_attestation, "local", ["p1", "p2"])
    assert err.code == "export_confirm_required" and err.data["label_default"] is True
    assert [v["video_id"] for v in err.data["voices"]] == ["p1", "p2"] and err.data["voices"][0]["speaker_name"] == "Asha"
    made = G.confirm_export("local", err.data["export_ref"], label_on=False, ip="1.2.3.4")
    assert made["covers"] == ["p1:h1", "p2:h2"] and made["voices_used"] == [voice]
    assert G.require_export_attestation("local", ["p1", "p2"])["id"] == made["id"]
    assert G.require_export_attestation("local", ["p2"])["id"] == made["id"]        # covered by the batch's
    assert G.export_label("local", "p1") is False
    content["p1"] = ("h1-changed", {voice})                                          # new edits: ask again
    assert _code(G.require_export_attestation, "local", ["p1"]).code == "export_confirm_required"
    assert _code(G.confirm_export, "local", "ex_nothing", True).status == 404


# ── promote, withdraw, the vendor deletes ────────────────────────────────────

def _passed_check(video="p1", speaker="A"):
    with database.tx() as c:
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, created_at) "
                  "VALUES ('cv_ok', 'local', ?, ?, 'a phrase', 'passed', 'verified', 'verified', ?)", (video, speaker, vg.iso(datetime.now(timezone.utc))))
    return "cv_ok"


def test_promote_needs_a_passed_own_voice_check(videos):
    voice = _clone()
    err = _code(G.promote, "local", voice)
    assert err.code == "own_voice_check_required" and err.data["video_id"] == "p1"
    check = _passed_check()
    got = G.promote("local", voice)
    assert (got["scope"], got["verified_consent_id"]) == ("library", check)
    assert G.check_scope(voice, "p2") is None


def test_withdraw_deletes_at_the_vendor_and_blocks_use(videos, monkeypatch):
    deleted = []
    monkeypatch.setattr(G, "vendor_delete", deleted.append)
    voice = _clone()
    got = G.withdraw("local", voice)
    assert deleted == [voice] and (got["status"], got["vendor_state"]) == ("withdrawn", "deleted")
    assert _code(G.check_scope, voice, "p1").data["reason"] == "withdrawn"


def test_a_vendor_delete_that_fails_stays_queued_and_the_start_drains_it(videos, monkeypatch):
    voice = _clone()

    def down(vid):
        raise RuntimeError("vendor down")
    monkeypatch.setattr(G, "vendor_delete", down)
    assert G.withdraw("local", voice)["vendor_state"] == "delete_queued"
    deleted = []
    monkeypatch.setattr(G, "vendor_delete", deleted.append)
    flags.set("voices.cloning_verified", "local", False)
    assert G.drain_vendor_deletes() == 0 and deleted == []                # flag off: nothing at the vendor
    flags.set("voices.cloning_verified", "local", True)
    assert G.drain_vendor_deletes() == 1 and deleted == [voice] and G.record(voice)["vendor_state"] == "deleted"


def test_backfill_records_a_clone_made_without_a_record(videos):
    repo.set_clone("p2", "A", "v-missed")
    assert G.backfill() == 1
    assert (G.record("v-missed")["scope"], G.record("v-missed")["origin"]) == ("video", "backfill")


# ── GuardedVoice: the vendor behind the guard ────────────────────────────────

def test_the_vendor_refuses_a_call_the_guard_did_not_pass(videos):
    from app.domain.models import EditPlan, Selection
    assert isinstance(main.voice, GuardedVoice) and main.clones._voice is main.voice
    record = repo.get("p1")
    plan = EditPlan(Selection(0.4, 1.3), "Hi", "mock")
    err = _code(main.voice.synthesize, record.source, plan, record.transcript)
    assert err.code == "guard_bypassed" and err.status == 500
    with vg.vendor_pass(vg.synth_key("p1")):
        assert main.voice.synthesize(record.source, plan, record.transcript).kind == "audio"
    assert _code(main.voice.create_clone, "voltage-p1-A", "/nowhere").code == "guard_bypassed"
    flags.set("voices.cloning_verified", "local", False)
    assert main.voice.synthesize(record.source, plan, record.transcript).kind == "audio"   # flag off: as before


def test_the_wrapper_is_the_adapter_in_every_other_way():
    assert hasattr(main.voice, "speak_like") == hasattr(main.voice.inner, "speak_like")
    assert main.voice.default_voice == main.voice.inner.default_voice
    main.voice.marker_for_test = 1
    assert main.voice.inner.marker_for_test == 1
    del main.voice.marker_for_test


# ── the routes ───────────────────────────────────────────────────────────────

def test_the_routes_attest_confirm_promote_withdraw(client, videos, monkeypatch):
    statement = client.get("/voices/attestation/statement").json()
    assert statement["version"] == vg.STATEMENT_VERSION and statement["accept"] == "Use this voice"
    voice = _clone()
    made = client.post(f"/videos/p1/voices/{voice}/attest", json={"choice": "my_voice", "statement_version": statement["version"]})
    assert made.status_code == 201 and made.json()["voice_id"] == voice
    stale = client.post(f"/videos/p1/voices/{voice}/attest", json={"choice": "my_voice", "statement_version": "old"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "statement_changed"
    monkeypatch.setattr(G, "export_content", lambda vid: ("h1", {voice}))
    with pytest.raises(VoiceGuardError) as asked:
        G.require_export_attestation("local", ["p1"])
    ok = client.post(f"/exports/{asked.value.data['export_ref']}/confirm", json={"label_on": True})
    assert ok.status_code == 201 and ok.json()["label_on"] is True
    refused = client.post(f"/voices/{voice}/promote")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "own_voice_check_required"
    _passed_check()
    promoted = client.post(f"/voices/{voice}/promote")
    assert promoted.status_code == 200 and promoted.json()["scope"] == "library"
    assert any(v["voice_id"] == voice for v in main._my_voices("local"))        # kept in My voices
    assert client.get("/voices/scopes").json()["voices"][0]["voice_id"] == voice
    deleted = []
    monkeypatch.setattr(G, "vendor_delete", deleted.append)
    gone = client.post(f"/voices/{voice}/withdraw")
    assert gone.status_code == 200 and gone.json()["status"] == "withdrawn" and deleted == [voice]


def test_the_admin_suspends_and_restores_cloning(client, videos):
    voice = _clone()
    assert client.post("/admin/users/local/suspend-cloning", json={"reason": ""}).status_code == 422
    done = client.post("/admin/users/local/suspend-cloning", json={"reason": "reported clip"}).json()
    assert done == {"owner": "local", "suspended": True, "voices_disabled": 1}
    assert G.record(voice)["status"] == "suspended"
    assert client.post("/admin/users/local/restore-cloning", json={"reason": "cleared"}).json()["voices_restored"] == 1
    assert client.post("/admin/users/local/clone-limits", json={"day": 9, "month": 40, "reason": "agency"}).json()["day"] == 9
    from app import admin
    assert [a["action"] for a in admin.recent_audit(database, 3, target="local")] == \
        ["voice_clone_limits", "voice_restore", "voice_suspend"]


def test_the_routes_are_not_there_with_the_flag_off(client, videos):
    flags.set("voices.cloning_verified", "local", False)
    assert client.get("/voices/attestation/statement").status_code == 404
    assert client.post("/voices/x/withdraw").status_code == 404
