"""Voice consent V1, step 3: every enforcement point asks the voice guard.

Two kinds of test. The structural ones read the code: every call that reaches
the voice vendor (synthesize, speech to speech, voice change, clone) sits in a
function that opens the guard's pass, the pipeline is reached only from
`_generate`, and every route that exports, shares, saves or clones a voice asks
the guard; a new route or call without it fails here. The behavioural ones
run the plan's checklist through the real routes and the agent's own tools,
with the mock vendor (no network, no spend) and `voices.cloning_verified` on.
"""
import ast
import inspect
import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

import app.api.main as main
from app.agent import tools as agent_tools
from app.agent.guards import GuardPause
from app.api.main import database, flags, repo
from app.domain.models import Selection
from app.media import ffmpeg
from app.safety import voice_guard as vg
from app.safety.voice_guard import VoiceGuardError
from tests.api.test_endpoints import WORDS, generate, upload

APP = Path(main.__file__).resolve().parents[1]
G = main.voice_guard
VENDOR = {"synthesize", "speak_like", "revoice", "create_clone"}


# ── structural: the code reaches the vendor only through the guard ───────────

def _calls(path: Path):
    """(enclosing function, method) for every `<x>.<vendor method>(...)` call in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def walk(node, where):
        for child in ast.iter_child_nodes(node):
            name = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{where}.{child.name}" if where else child.name
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in VENDOR:
                found.append((where, child.func.attr))
            walk(child, name)
    walk(tree, "")
    return found


# Where the app calls the vendor, and why each is behind the guard.
ALLOWED = {
    ("api/main.py", "add_my_voice.make", "create_clone"): "vendor_pass(clone_key)",
    ("api/main.py", "add_my_voice_from_speaker", "create_clone"): "vendor_pass(clone_key)",
    ("orchestrator/clones.py", "CloneService.resolve", "create_clone"): "the guard's clone_pass",
    ("orchestrator/pipeline.py", "_speak_like", "speak_like"): "only from run_edit",
    ("orchestrator/pipeline.py", "_revoiced", "revoice"): "only from run_edit",
    ("orchestrator/pipeline.py", "run_edit", "synthesize"): "only from main._generate, inside its pass",
}


def test_every_vendor_call_in_the_app_is_behind_the_guard():
    seen = set()
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith(("adapters/", "bench/", "tools/")) or rel == "safety/voice_guard.py":
            continue      # the vendor itself, offline benches and command-line tools (no route reaches them)
        for where, method in _calls(path):
            key = (rel, where, method)
            assert key in ALLOWED, f"{rel}: {where} calls the voice vendor ({method}) without the voice guard"
            seen.add(key)
    assert seen == set(ALLOWED)
    src = inspect.getsource(main.add_my_voice) + inspect.getsource(main.add_my_voice_from_speaker)
    assert src.count("vendor_pass(") >= 2
    from app.orchestrator import clones
    assert "clone_pass(" in inspect.getsource(clones.CloneService.resolve)


def test_the_pipeline_is_reached_only_from_generate_and_generate_asks_the_guard():
    callers = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in (
                    "run_edit", "_speak_like", "_revoiced"):
                callers.append(path.relative_to(APP).as_posix())
    assert sorted(set(callers)) == ["api/main.py", "orchestrator/pipeline.py"]
    src = inspect.getsource(main._generate)
    assert "voice_guard.before_synthesis(" in src and "synth_key(" in src and "voice_guard.log_synthesis(" in src
    assert src.count("run_edit(") == 1


# Route endpoints whose code exports, shares, saves or clones a voice: each asks the guard.
MARKERS = ("export_engine.start(", "_render_job(", "shares_store.create", "_set_my_voices(", "create_clone(")
EXEMPT = {
    "add_my_voice_from_preview": "a designed voice: not a clone, nothing to attest",
    "share_batch_export": "the export it shares was confirmed when it was made (start_batch_export)",
    "start_render": "a preview render inside the editor, never a file that leaves it",
    "restore_from_bin": "puts back what was there; every use is checked again",
}


def _sensitive_routes():
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        try:
            src = inspect.getsource(route.endpoint)
        except (OSError, TypeError):
            continue
        if any(m in src for m in MARKERS):
            yield route, src


def test_every_route_that_exports_shares_saves_or_clones_asks_the_guard():
    found = {}
    for route, src in _sensitive_routes():
        name = route.endpoint.__name__
        found[name] = route.path
        if name in EXEMPT:
            continue
        assert "voice_guard" in src or "_guard_" in src, f"{route.path} ({name}) does not ask the voice guard"
    for must in ("export_project", "start_batch_export", "create_share", "create_review_link", "add_my_voice",
                 "add_my_voice_from_speaker", "keep_made_voice"):
        assert must in found or must in {"create_review_link"}, must


def test_the_agents_voicing_and_cloning_tools_go_through_the_guard():
    """A tool that reaches `_generate` or `_voice_for` is guarded where they are; the
    agent's own list and pick are filtered by scope (`voice_refusal`)."""
    reach = {t.name for t in agent_tools.TOOLS
             if any(s in inspect.getsource(t.run) for s in ("wb.generate", "wb.held_take", "wb.voice_for"))}
    assert reach == {"synthesize_take", "clone_speaker"}
    assert "_usable(" in inspect.getsource(agent_tools._list_voices) and "voice_refusal" in inspect.getsource(agent_tools._usable)
    assert "voice_refusal" in inspect.getsource(agent_tools._synthesize_take)
    assert main._workbench().voice_refusal is not None


# ── behavioural: the plan's checklist ────────────────────────────────────────

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture()
def videos(client, sample_video):
    """p1 and p2 in project f1, p3 a variant of p1, p4 the Hindi version of p1."""
    client.post("/projects", json={"name": "Diwali"})
    for _ in range(2):
        with open(sample_video, "rb") as f:
            made = client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "true", "project_id": "f1"})
        assert made.status_code == 200, made.text
    assert client.post("/videos/p1/variants").status_code == 200
    language = main._make_variant("p1", repo.get("p1"), "local", copy_plan=False)
    repo.link_language(language, "p1", "hi", 0)
    return {"variant": "p3", "language": language}


SPEAKER = "_"          # the canned clip has no diarized speakers: its one voice is the whole clip's


def _clone(voice_id="v-clone", video="p1", label=SPEAKER):
    """p1's speaker cloned (the clone made, its record written), as the clone path leaves it."""
    repo.set_clone(video, label, voice_id)
    G.record_voice("local", voice_id, kind="cloned", scope="video", origin="clone", source_video_id=video,
                   speaker_label=label, speaker_name="Asha")
    main.voice.register_clone(voice_id)
    return voice_id


def _attest(voice_id, video="p1", client=None):
    G.attest("local", video, voice_id, "my_voice", vg.STATEMENT_VERSION)


def _err(fn, *a, **kw) -> VoiceGuardError:
    with pytest.raises(VoiceGuardError) as caught:
        fn(*a, **kw)
    return caught.value


def _turn(video_id, *, batch=False):
    from app.agent.guards import TurnBudget
    from app.agent.tools import Turn
    plan = main._turn_plan(video_id, "voice it")
    return Turn(project_id=video_id, record=repo.get(video_id), plan_id=plan.plan_id, autonomy="draft", spend_approved=True,
                budget=TurnBudget(usd=5.0), started_at=main._now(), batch=batch)


def _say(voice_id, video_id="p1", batch=False, text="Get 30% off today only."):
    return agent_tools._synthesize_take(main._workbench(), _turn(video_id, batch=batch),
                                        {"text": text, "voice_id": voice_id, "line": 1, "fit": "fit", "picture": "default",
                                         "model": "default", "mix": "replace", "direction": ""})


def test_voicing_a_clone_with_no_attestation_asks_then_works(videos):
    voice = _clone()
    err = _err(generate, voice_id=voice)
    assert err.code == "attestation_required" and err.data["voice"] == voice
    _attest(voice)
    made = generate(voice_id=voice)
    with database.tx() as c:
        row = dict(c.execute("SELECT * FROM synthesis_log ORDER BY created_at DESC LIMIT 1").fetchone())
        checks = c.execute("SELECT COUNT(*) FROM line_checks").fetchone()[0]
    assert row["take_id"] == made["candidate_id"] and row["voice_id"] == voice and row["attestation_id"] and checks == 1


def test_the_agent_pauses_on_the_attestation_card_never_prose(client, videos, monkeypatch):
    from tests.agent.conftest import reply, text as said
    from tests.api.test_endpoints import take, turn as scripted
    voice = _clone()
    main._set_my_voices("local", [{"voice_id": voice, "name": "Asha", "kind": "cloned", "seconds": 12.0}])   # one Voltage may pick
    result = scripted(client, monkeypatch, [reply(take(voice_id=voice, line=1), stop="tool_use"), reply(said("Done."))])
    question = result["question"]
    assert question["kind"] == "attestation_required" and question["gate"] is False
    assert question["attestation"]["voice"] == voice and question["attestation"]["statement_version"] == vg.STATEMENT_VERSION
    assert question["text"] == "Use Asha's voice?" and question["options"] == ["Use this voice", "Cancel"]
    assert result["calls"] == 1                                  # the turn stopped on the card: Voltage never narrated it
    assert result["reply"] in (None, "")


def test_the_fast_path_hands_an_attestation_to_the_full_turn(videos):
    from app.agent import fastpath
    voice = _clone()
    out = fastpath.voice(main._workbench(), _turn("p1"), line_no=1, item_id=None, text="Get 30% off.", voice_id=voice,
                         direction=None)
    assert not out.made


def test_a_video_voice_on_another_video_is_out_of_scope_everywhere(client, videos):
    voice = _clone()
    _attest(voice)
    assert _err(generate, voice_id=voice, project_id="p2").code == "voice_out_of_scope"         # the pipeline itself
    main._set_my_voices("local", [{"voice_id": voice, "name": "Asha", "kind": "cloned", "seconds": 12.0}])
    listed = agent_tools._list_voices(main._workbench(), _turn("p2"), {}).text
    assert voice not in listed                                                                 # the agent cannot pick it
    assert voice in agent_tools._list_voices(main._workbench(), _turn(videos["variant"]), {}).text
    for batch in (False, True):                                                                # the agent and a batch child
        said = _say(voice, "p2", batch=batch)
        assert vg.OUT_OF_SCOPE in said.text and not said.cost_usd
    from app.store.repository import Speaker
    real = repo.speakers
    repo.speakers = lambda vid: [Speaker("A", "Asha")] if vid == "p2" else real(vid)
    try:
        picked = client.put("/videos/p2/speakers/A", json={"voice_id": voice})        # picked by hand for a speaker
    finally:
        del repo.speakers
    assert picked.status_code == 403 and picked.json()["detail"]["code"] == "voice_out_of_scope"


def test_variants_and_language_versions_can_use_the_source_voice(videos):
    voice = _clone()
    _attest(voice)
    for vid in (videos["variant"], videos["language"]):
        assert generate(voice_id=voice, project_id=vid)["candidate_id"]


def _ship(client, video, voice):
    made = generate(voice_id=voice, project_id=video)
    assert client.post(f"/videos/{video}/edits", json={"candidate_id": made["candidate_id"]}).status_code == 200


def test_an_export_with_a_cloned_voice_needs_the_confirmation_and_a_batch_asks_once(client, videos):
    voice = _clone()
    _attest(voice)
    _ship(client, "p1", voice)
    asked = client.post("/videos/p1/export", json={"purpose": "export"})
    assert asked.status_code == 409 and asked.json()["detail"]["code"] == "export_confirm_required"
    ref = asked.json()["detail"]["export_ref"]
    assert client.post(f"/exports/{ref}/confirm", json={"label_on": True}).status_code == 201
    assert client.post("/videos/p1/export", json={"purpose": "export"}).status_code in (200, 202)
    assert client.post("/videos/p1/export", json={}).status_code in (200, 202)                 # a preview never asks
    # A batch: p1 and its variant, both in the clone's voice, one confirmation for both.
    repo.set_folder(videos["variant"], "f1")
    _ship(client, videos["variant"], voice)
    preset = client.post("/projects/f1/export-presets", json={"name": "Reel", "platform": "reels"}).json()
    body = {"video_ids": ["p1", videos["variant"]], "preset_ids": [preset["preset_id"]]}
    batch = client.post("/projects/f1/exports", json=body)
    assert batch.status_code == 409
    detail = batch.json()["detail"]
    assert detail["videos"] == ["p1", videos["variant"]] and len({v["video_id"] for v in detail["voices"]}) == 2
    assert client.post(f"/exports/{detail['export_ref']}/confirm", json={"label_on": False}).status_code == 201
    assert G.require_export_attestation("local", ["p1", videos["variant"]])["label_on"] == 0     # asked once for both
    # A share link people can watch, and a review link with Download, are exports too; a review link without it is not.
    other = _clone("v-clone-2", video="p2")
    _attest(other, video="p2")
    _ship(client, "p2", other)
    link = client.post("/projects/f1/shares", json={"scope": "video", "target": "p2"})
    assert link.status_code == 409 and link.json()["detail"]["code"] == "export_confirm_required"
    review = client.post("/videos/p2/review-links", json={"name": "Ravi", "allow_download": True})
    assert review.status_code == 409 and review.json()["detail"]["export_ref"] == link.json()["detail"]["export_ref"]
    assert client.post("/videos/p2/review-links", json={"name": "Ravi"}).status_code == 201
    assert client.post(f"/exports/{link.json()['detail']['export_ref']}/confirm", json={}).status_code == 201
    assert client.post("/projects/f1/shares", json={"scope": "video", "target": "p2"}).status_code == 201


def test_save_to_my_voices_needs_a_passed_own_voice_check(client, videos, monkeypatch):
    from app.store.repository import Speaker
    real = repo.speakers
    monkeypatch.setattr(repo, "speakers", lambda vid: [Speaker("A", "Asha")] if vid == "p1" else real(vid))
    voice = _clone(label="A")
    keep = client.post("/voices/mine/keep", json={"voice_id": voice, "name": "Asha"})
    assert keep.status_code == 403 and keep.json()["detail"]["code"] == "own_voice_check_required"
    spoke = client.post("/voices/mine/from-speaker", json={"video_id": "p1", "label": "A", "name": "Asha 2", "consent": True})
    assert spoke.status_code == 403 and spoke.json()["detail"]["code"] == "own_voice_check_required", spoke.text
    with database.tx() as c:
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, created_at) "
                  "VALUES ('cv_2', 'local', 'p1', 'A', 'x', 'passed', 'verified', 'verified', ?)", (main._now(),))
    kept = client.post("/voices/mine/keep", json={"voice_id": voice, "name": "Asha"})
    assert kept.status_code == 201
    assert G.record(voice)["scope"] == "library" and G.record(voice)["verified_consent_id"] == "cv_2"


def test_withdraw_deletes_the_vendor_voice_and_blocks_use(client, videos, monkeypatch):
    deleted = []
    monkeypatch.setattr(main.voice, "delete_voice", deleted.append, raising=False)
    voice = _clone()
    _attest(voice)
    gone = client.post(f"/voices/{voice}/withdraw")
    assert gone.status_code == 200 and deleted == [voice]
    assert repo.clones("p1").get(SPEAKER) is None                     # the speaker can be cloned again, with new checks
    err = _err(generate, voice_id=voice)
    assert (err.code, err.data["reason"]) == ("voice_unavailable", "withdrawn")


def test_a_new_statement_version_forces_reconfirmation(videos, monkeypatch):
    voice = _clone()
    _attest(voice)
    assert generate(voice_id=voice)["candidate_id"]
    monkeypatch.setattr(vg, "STATEMENT_VERSION", "2027-01-01")
    assert _err(generate, voice_id=voice).code == "attestation_required"


def test_cloning_a_speaker_needs_can_clone_and_an_attestation_before_the_vendor(videos, monkeypatch):
    made = []
    real = main.voice.inner.create_clone
    monkeypatch.setattr(main.voice.inner, "create_clone", lambda name, ref: made.append(name) or real(name, ref))
    monkeypatch.setattr(main.clones, "_min", 0.5)
    with database.tx() as c:
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, created_at) "
                  "VALUES ('cv_3', 'local', 'p1', NULL, 'x', 'passed', 'verified', 'verified', ?)", (main._now(),))
    record = repo.get("p1")
    label = next(iter({w.speaker for w in record.transcript.words if w.speaker} or {None}))
    err = _err(main._voice_for, "p1", record, Selection(*WORDS), "mock", label)
    assert err.code == "attestation_required" and made == []                       # nothing reached the vendor
    G.attest("local", "p1", err.data["voice"], "my_voice", vg.STATEMENT_VERSION)
    choice = main._voice_for("p1", record, Selection(*WORDS), "mock", label)
    assert choice.cloned and made and G.record(choice.voice_id)["scope"] == "video"
    G.suspend("local", "test", "admin")
    repo.set_clone("p1", err.data["voice"], None)
    assert _err(main._voice_for, "p1", record, Selection(*WORDS), "mock", label).code == "clone_not_allowed"


def test_with_the_flag_off_nothing_is_asked(videos):
    flags.set("voices.cloning_verified", "local", False)
    voice = _clone()
    assert generate(voice_id=voice, project_id="p2")["candidate_id"]
    with database.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM line_checks").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM synthesis_log").fetchone()[0] == 0
