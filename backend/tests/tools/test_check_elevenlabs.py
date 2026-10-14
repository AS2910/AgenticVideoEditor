"""The key check names what a restricted key lacks, and never prints the key."""
from app.tools import check_elevenlabs as tool

KEY = "sk_test_never_real_0123456789"
LACKS = '{"detail":{"status":"missing_permissions","message":"The API key you used is missing the permission %s to execute this operation."}}'
SUBSCRIPTION = {"tier": "creator", "status": "active", "character_count": 1200, "character_limit": 121000,
                "can_use_instant_voice_cloning": True, "voice_slots_used": 2, "voice_limit": 30}


def fake(answers):
    def get(api_key, path):
        return answers[path]
    return get


FULL = {
    "/v1/user/subscription": (200, "{}", SUBSCRIPTION),
    "/v2/voices?page_size=1": (200, "{}", {}),
    "/v1/models": (200, "[]", None),
}


def test_a_full_key_passes_and_the_plan_is_read():
    findings, plan = tool.check(KEY, fake(FULL))
    assert all(f.ok for f in findings)
    text = tool.report(findings, plan)
    assert "Plan: creator (active)" in text and "Instant voice cloning: yes" in text
    assert "can do everything Voltage reads" in text


def test_a_restricted_key_names_each_missing_permission_and_how_to_fix_it():
    answers = {
        "/v1/user/subscription": (401, LACKS % "user_read", None),
        "/v2/voices?page_size=1": (401, LACKS % "voices_read", None),
        "/v1/models": (401, LACKS % "models_read", None),
    }
    findings, plan = tool.check(KEY, fake(answers))
    assert [f.ok for f in findings] == [False, False, False] and plan == {}
    text = tool.report(findings, plan)
    assert "the key lacks voices_read" in text
    assert "allow models_read, user_read, voices_read" in text


def test_a_rejected_key_is_not_called_a_missing_permission():
    answers = {p: (401, "unauthorized", None) for p in FULL}
    findings, _ = tool.check(KEY, fake(answers))
    assert all(f.detail == "the key was rejected" for f in findings)


def test_the_report_says_what_it_did_not_test():
    text = tool.report(*tool.check(KEY, fake(FULL)))
    assert "voices_write" in text and "not tested here" in text


def test_no_key_is_a_plain_sentence(monkeypatch, capsys):
    monkeypatch.setattr(tool, "load_settings", lambda: type("S", (), {"elevenlabs_api_key": None})())
    assert tool.main() == 1
    assert "offline mock voice" in capsys.readouterr().out
