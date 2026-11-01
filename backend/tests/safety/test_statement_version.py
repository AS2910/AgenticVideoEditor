"""Voice consent V1, step 8: the consent wording is pinned to its version.

`app/safety/voice_guard.py` holds the attestation statement and the export
reminder (STATEMENT, EXPORT_STATEMENT) and one STATEMENT_VERSION for both. A
person's confirmation counts only for the version they saw, so changing a word
without bumping the version would hold people to words they never read. Here
each version is pinned to a fingerprint of its words: change the words and
this fails until the version is bumped and the new pair is added below (never
edit an old pair). RUNBOOK.md, "Changing the consent wording".
"""
import pytest

from app.media import ffmpeg
from app.safety import voice_guard as vg
from tests.safety.test_voice_guard import _clone, _code, videos  # noqa: F401 (the fixture)

# version -> statement_hash() of the words people confirmed under it. Add a line per bump; never edit one.
PINNED = {
    "2026-10-31": "9d60ed759355b51cd3b1c0e27cb0cca683a477d60dc2022e5efe0f7d1c4982e9",
}

BUMP = ("The attestation or export reminder wording changed. Bump STATEMENT_VERSION in app/safety/voice_guard.py "
        "and add the new version with vg.statement_hash() to PINNED here (RUNBOOK.md, Changing the consent wording).")


def test_the_wording_people_confirm_is_the_wording_pinned_to_its_version():
    assert vg.STATEMENT_VERSION in PINNED, BUMP
    assert vg.statement_hash() == PINNED[vg.STATEMENT_VERSION], BUMP
    # The current version is the newest pinned one, and no two versions share their words.
    assert vg.STATEMENT_VERSION == max(PINNED)
    assert len(set(PINNED.values())) == len(PINNED)


@pytest.mark.parametrize("change", [
    lambda: vg.STATEMENT.__setitem__("confirm", vg.STATEMENT["confirm"].replace("rights and consent", "rights")),
    lambda: vg.STATEMENT["choices"][1].__setitem__("label", "I have permission"),
    lambda: vg.EXPORT_STATEMENT.__setitem__("confirm", "I have permission"),
])
def test_changing_a_word_without_bumping_the_version_fails_the_pin(change, monkeypatch):
    import copy
    monkeypatch.setattr(vg, "STATEMENT", copy.deepcopy(vg.STATEMENT))
    monkeypatch.setattr(vg, "EXPORT_STATEMENT", copy.deepcopy(vg.EXPORT_STATEMENT))
    change()
    assert vg.statement_hash() != PINNED[vg.STATEMENT_VERSION]


def test_the_statement_route_serves_the_pinned_words(client):
    import app.api.main as main
    served = main.voice_guard.statement()
    assert served["version"] == vg.STATEMENT_VERSION and served["export"]["version"] == vg.STATEMENT_VERSION
    assert served["confirm"] == vg.STATEMENT["confirm"] and served["export"]["confirm"] == vg.EXPORT_STATEMENT["confirm"]


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
def test_a_bumped_version_asks_again_for_the_voice_and_for_the_export(videos, monkeypatch):  # noqa: F811
    """The checklist test, both moments: an attestation and an export confirmation under the old
    version stop counting; confirming under the new one works again."""
    import app.api.main as main
    guard = main.voice_guard
    voice = _clone()
    guard.attest("local", "p1", voice, "my_voice", vg.STATEMENT_VERSION)
    monkeypatch.setattr(guard, "export_content", lambda vid: ("h1", {voice}))
    asked = _code(guard.require_export_attestation, "local", ["p1"])
    guard.confirm_export("local", asked.data["export_ref"], label_on=True)
    assert guard.require_attestation("local", "p1", voice)                     # the attestation it found
    assert guard.require_export_attestation("local", ["p1"]) is not None

    monkeypatch.setattr(vg, "STATEMENT_VERSION", "2099-01-01")
    err = _code(guard.require_attestation, "local", "p1", voice)
    assert err.code == "attestation_required" and err.data["statement_version"] == "2099-01-01"
    again = _code(guard.require_export_attestation, "local", ["p1"])
    assert again.code == "export_confirm_required" and again.data["statement_version"] == "2099-01-01"
    assert _code(guard.attest, "local", "p1", voice, "my_voice", "2026-10-31").code == "statement_changed"

    guard.attest("local", "p1", voice, "my_voice", "2099-01-01")
    guard.confirm_export("local", again.data["export_ref"], label_on=True)
    assert guard.require_attestation("local", "p1", voice)                     # the attestation it found
    assert guard.require_export_attestation("local", ["p1"])["statement_version"] == "2099-01-01"
