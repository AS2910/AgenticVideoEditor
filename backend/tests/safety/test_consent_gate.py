"""Run 4 item 2: the consent gate's rules, one at a time (app.safety.consent),
the flag, and migration 0039. No model and no vendor: every part is injected."""
import random
from pathlib import Path

import pytest

from app.flags import KNOWN, PROFILES, FlagStore
from app.safety import consent
from app.safety.consent import (
    MAX_WER,
    MIN_SECONDS,
    PASS_AT,
    REVIEW_FROM,
    ConsentVerifier,
    decide,
    normalise,
    phrase,
    wer,
)
from app.store.db import Database

TEXT = "Purple kettle river tiger window salad pencil morning garden quiet."


def test_a_phrase_is_8_to_12_different_plain_words():
    rng = random.Random(7)
    for _ in range(200):
        said = phrase(rng)
        words = normalise(said)
        assert 8 <= len(words) <= 12 and len(set(words)) == len(words)
        assert set(words) <= set(consent.WORDS) and said.endswith(".") and said[0].isupper()
    assert phrase() != phrase()                      # the system's randomness: fresh each time


def test_the_word_list_has_no_repeats_numbers_or_homophones():
    assert len(set(consent.WORDS)) == len(consent.WORDS) >= 120
    assert not {"two", "to", "too", "four", "for", "one", "right", "write", "sea", "see", "blue", "blew"} & set(consent.WORDS)
    assert all(w.isalpha() and w.islower() for w in consent.WORDS)


def test_normalising_ignores_case_punctuation_and_spacing():
    assert normalise("  Purple, KETTLE... river-tiger!  ") == ["purple", "kettle", "river", "tiger"]
    assert normalise("It’s fine") == normalise("its fine") == ["its", "fine"]


def test_word_error_rate():
    assert wer(TEXT, TEXT.lower().rstrip(".")) == 0.0
    assert wer(TEXT, TEXT.replace("tiger", "tigers")) == pytest.approx(0.1)          # one substitution in ten
    assert wer(TEXT, TEXT.replace("tiger window ", "")) == pytest.approx(0.2)        # two deletions
    assert wer(TEXT, "um " + TEXT) == pytest.approx(0.1)                             # one insertion
    assert wer(TEXT, "") == 1.0 and wer("", "") == 0.0


def test_the_length_rule():
    short = decide(TEXT, seconds=MIN_SECONDS - 0.1, heard=TEXT, similarity=0.99)
    assert short.status == "failed" and short.rule == "length" and "at least 4 s" in short.reason and short.tip
    unread = decide(TEXT, seconds=None, heard=TEXT, similarity=0.99)
    assert unread.status == "failed" and unread.rule == "length"
    assert decide(TEXT, seconds=MIN_SECONDS, heard=TEXT, similarity=0.99).passed


def test_the_words_rule():
    two_wrong = TEXT.replace("tiger", "taker").replace("salad", "solid")
    failed = decide(TEXT, seconds=5.0, heard=two_wrong, similarity=0.99)
    assert failed.status == "failed" and failed.rule == "words" and failed.wer == pytest.approx(MAX_WER)
    assert "did not match" in failed.reason and "Read every word" in failed.tip
    one_wrong = decide(TEXT, seconds=5.0, heard=TEXT.replace("tiger", "taker"), similarity=0.99)
    assert one_wrong.passed and one_wrong.wer == pytest.approx(0.1)
    # The words are checked before the voice: a perfect voice does not rescue the wrong words.
    assert decide(TEXT, seconds=5.0, heard="hello there", similarity=1.0).rule == "words"


def test_the_voice_rule_and_its_review_band():
    at = lambda sim: decide(TEXT, seconds=5.0, heard=TEXT, similarity=sim)
    assert at(PASS_AT).status == "passed" and at(0.99).status == "passed"
    assert at(PASS_AT - 0.001).status == "review" and at(REVIEW_FROM).status == "review"
    low = at(REVIEW_FROM - 0.001)
    assert low.status == "failed" and low.rule == "voice" and "does not match the speaker" in low.reason and low.tip
    assert at(0.88).similarity == 0.88 and at(0.88).wer == 0.0
    assert 0 < REVIEW_FROM < PASS_AT < 1


def test_what_cannot_be_measured_goes_to_a_person():
    no_voice = decide(TEXT, seconds=5.0, heard=TEXT, similarity=None)
    assert no_voice.status == "review" and no_voice.rule == "unmeasured" and "the voice" in no_voice.reason
    no_words = decide(TEXT, seconds=5.0, heard=None, similarity=0.99)
    assert no_words.status == "review" and "the words" in no_words.reason


def test_the_verifier_calls_each_part_only_when_it_counts(tmp_path):
    calls = []
    v = ConsentVerifier(transcribe=lambda p, vid: calls.append(("hear", vid)) or TEXT,
                        similarity=lambda ref, rec: calls.append(("sim", ref.name)) or 0.95,
                        seconds_of=lambda p: 5.0, asr_model="openai:whisper-1", speaker_model="wavlm")
    rec, ref = tmp_path / "rec.webm", tmp_path / "ref.wav"
    assert v.verify(rec, TEXT, ref, "p1").passed and calls == [("hear", "p1"), ("sim", "ref.wav")]
    calls.clear()
    assert v.verify(rec, TEXT, None, "p1").status == "review" and calls == [("hear", "p1")]   # no source audio to compare
    calls.clear()
    short = ConsentVerifier(transcribe=lambda p, vid: calls.append("hear") or TEXT, similarity=lambda a, b: 1.0,
                            seconds_of=lambda p: 2.0)
    assert short.verify(rec, TEXT, ref).rule == "length" and calls == []                  # nothing paid for a short one
    broken = ConsentVerifier(transcribe=lambda p, vid: TEXT, similarity=lambda a, b: 1.0,
                             seconds_of=lambda p: (_ for _ in ()).throw(ValueError("no audio")))
    assert broken.verify(Path("x"), TEXT, ref).status == "failed"


def test_the_flag_is_off_by_default_and_not_in_the_public_profile():
    assert "voices.cloning_verified" in KNOWN
    assert "voices.cloning_verified" not in PROFILES["public"]
    store = FlagStore(Database(), ("local",), "public")
    assert not store.enabled("voices.cloning_verified", "local") and not store.enabled("voices.cloning_verified", "acct:x")
    assert store.enabled("voices.cloning", "local")                 # the other voice flag keeps its default
    store.set("voices.cloning_verified", "*", True)
    assert store.enabled("voices.cloning_verified", "acct:x")


def test_migration_0039_adds_the_evidence_and_keeps_it(tmp_path):
    from app.store import migrate
    from app.store.migrations import m0039_consent_verified as m39
    conn = migrate.connect(str(tmp_path / "a.db"))
    migrate.up(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(liveness_attempts)")}
    assert {"method", "heard", "wer", "similarity", "seconds", "asr_model", "speaker_model", "pass_at", "review_from",
            "expires_at", "reviewed_by", "review_reason", "reviewed_at"} <= cols
    migrate.down_to(conn, 37)
    assert "similarity" not in {r[1] for r in conn.execute("PRAGMA table_info(liveness_attempts)")}
    migrate.up(conn)
    conn.execute("INSERT INTO liveness_attempts (id, owner, video_id, sentence, status, method, created_at) "
                 "VALUES ('cv_1', 'a', 'p1', 'x', 'passed', 'verified', 't')")
    with pytest.raises(RuntimeError, match="refusing"):
        m39.down(conn)
