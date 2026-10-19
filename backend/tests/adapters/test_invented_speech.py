"""Bug 3 (2026-10-19): "謝您的觀看" on a silent stretch.

Whisper heard "多謝您的觀看" (Chinese for "thanks for watching") at 5.5–6.9 s
of a clip with no speech there. The segment was dropped (no_speech_prob 0.61),
but five of its words were zero-length at 6.90–6.90, on the segment's edge,
and the word filter's strict overlap test kept them."""
import json
from pathlib import Path

import pytest

from app.adapters import openai_whisper as w
from app.domain.models import Statement, Transcript, Word

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_this_clips_own_whisper_answer_leaves_nothing_in_the_transcript():
    payload = json.loads((FIXTURES / "whisper-silent-tail-zh.json").read_text())
    assert payload["segments"][0]["text"] == "多謝您的觀看"
    assert sum(1 for x in payload["words"] if x["start"] == x["end"]) == 5   # the zero-length words on the edge
    t = w.to_transcript(payload)
    assert t.statements == () and t.words == ()


def test_this_clips_answer_and_audio_through_the_whole_filter_leave_nothing():
    """The energy check alone would keep this tail: the clip has ambient sound there, above the
    floor. The transcript filter is what has to drop it — and with it, every one of its words."""
    payload = json.loads((FIXTURES / "whisper-silent-tail-zh.json").read_text())
    tail = Transcript(words=(Word("多謝您的觀看", 5.5, 6.9),), statements=(Statement("多謝您的觀看", 5.5, 6.9),))
    assert w.without_silent_speech(tail, FIXTURES / "silent-tail-zh.wav").statements != ()   # energy alone: kept
    kept = w.without_silent_speech(w.to_transcript(payload), FIXTURES / "silent-tail-zh.wav")
    assert kept.statements == () and kept.words == ()


def _speech_then_tail(tail_text: str, nsp: float, lp: float, language="english", speech="Get twenty percent off today only."):
    words = [{"word": x, "start": 0.2 + i * 0.3, "end": 0.45 + i * 0.3} for i, x in enumerate(speech.split())]
    tail = tail_text.split() if " " in tail_text else list(tail_text)
    # Whisper's habit: the first word takes the span, the rest are zero-length on its end.
    words += [{"word": tail[0], "start": 5.5, "end": 6.9}] + [{"word": x, "start": 6.9, "end": 6.9} for x in tail[1:]]
    return {"language": language, "segments": [
        {"start": 0.2, "end": 2.3, "text": speech, "no_speech_prob": 0.01, "avg_logprob": -0.2, "compression_ratio": 1.1},
        {"start": 5.5, "end": 6.9, "text": tail_text, "no_speech_prob": nsp, "avg_logprob": lp, "compression_ratio": 0.7},
    ], "words": words}


@pytest.mark.parametrize("tail", [
    "Thanks for watching!", "Please subscribe to my channel", "多謝您的觀看", "谢谢观看", "ご視聴ありがとうございました",
    "시청해주셔서 감사합니다", "देखने के लिए धन्यवाद", "चैनल को सब्सक्राइब करें", "Gracias por ver", "Спасибо за просмотр",
])
def test_a_sign_off_on_a_silent_tail_is_dropped_in_any_language(tail):
    # Whisper doubts it a little (0.3), not enough for the general bar (0.6): the sign-off rule catches it.
    t = w.to_transcript(_speech_then_tail(tail, nsp=0.3, lp=-0.6))
    assert [s.text for s in t.statements] == ["Get twenty percent off today only."]
    assert all(x.end <= 2.5 for x in t.words), [x.text for x in t.words if x.end > 2.5]


def test_another_script_than_the_clip_with_some_doubt_is_dropped_but_confident_code_switching_stays():
    shaky = _speech_then_tail("这是一个美丽的地方", nsp=0.35, lp=-0.5)
    assert [s.text for s in w.to_transcript(shaky).statements] == ["Get twenty percent off today only."]
    # Hinglish: a Hindi clip with an English phrase said with confidence keeps it.
    confident = _speech_then_tail("Thirty percent off on everything", nsp=0.02, lp=-0.25, language="hindi",
                                  speech="आज सब कुछ सस्ता है और बहुत अच्छा है")
    assert [s.text for s in w.to_transcript(confident).statements] == ["आज सब कुछ सस्ता है और बहुत अच्छा है", "Thirty percent off on everything"]


def test_real_speech_that_mentions_watching_or_thanks_is_kept():
    payload = _speech_then_tail("We are watching the sunset over the hills of Goa with my whole family tonight", nsp=0.3, lp=-0.4)
    assert len(w.to_transcript(payload).statements) == 2


def test_the_scripts_are_read_from_the_letters():
    assert w.script_of("多謝您的觀看") == "han"
    assert w.script_of("ご視聴ありがとうございました") == "kana"
    assert w.script_of("시청해주셔서") == "hangul"
    assert w.script_of("धन्यवाद") == "devanagari"
    assert w.script_of("Thanks") == "latin" and w.script_of("123 !") is None
