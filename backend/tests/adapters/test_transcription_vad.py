"""Run 5 item 4: transcription that makes things up.

Silence is never sent to be transcribed (voice activity detection,
`app/media/vad.py`); what comes back is screened for the phrases and captions
Whisper invents, in any language. Every vendor reply here is mocked; the clips
are made with ffmpeg. The bar for the four clips: zero invented lines.
"""
import numpy as np
import pytest

from app.adapters.openai_whisper import WhisperTranscriptionAdapter, doubtful, to_transcript
from app.media import ffmpeg, vad
from tests.factories import SPEECH_LIKE, audio_clip, make_source, video_with

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")

# Low hiss under everything: a phone in a quiet room, not digital zero.
HISS = "0.002*(random(0)-0.5)"
# Two notes of a steady synth pad, loud: a music bed with nobody speaking.
MUSIC = "0.25*(sin(2*PI*220*t)+0.6*sin(2*PI*330*t)+0.4*sin(2*PI*440*t))"


def _source(path, seconds):
    from app.domain.models import MediaArtifact
    return make_source(duration=seconds, media=MediaArtifact(
        kind="video", sha256="4" * 64, path=str(path), duration=seconds, container="mp4"))


def _never(*a):
    raise AssertionError("nothing here should be sent to be transcribed")


def _no_turns(*a):
    return {"segments": []}


def _seg(text, start, end, **numbers):
    return {"text": text, "start": start, "end": end, **numbers}


def _words(text, start, end):
    parts = text.split()
    step = (end - start) / len(parts)
    return [{"word": w, "start": start + i * step, "end": start + (i + 1) * step} for i, w in enumerate(parts)]


def _sent_seconds(path):
    return len(vad.read_wav(path)) / vad.RATE


# ── the detector ────────────────────────────────────────────────────────────

def test_silence_has_no_speech_spans():
    assert vad.speech_spans(np.zeros(vad.RATE * 10, dtype=np.float32)) == []


def test_speech_then_a_long_silence_keeps_only_the_speech():
    rate = vad.RATE
    t = np.arange(rate * 20) / rate
    voice = 0.3 * (np.sin(2 * np.pi * 140 * t) + 0.5 * np.sin(2 * np.pi * 700 * t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2
    x = np.where((t >= 1) & (t < 4), voice, 0.0) + np.random.default_rng(1).standard_normal(len(t)) * 0.001
    [(a, b)] = vad.speech_spans(x.astype(np.float32))
    assert 0.5 <= a <= 1.0 and 4.0 <= b <= 4.6


def test_the_time_map_puts_every_time_back_on_the_clip_exactly():
    x = np.zeros(vad.RATE * 30, dtype=np.float32)
    joined, mapping = vad.cut(x, [(2.0, 5.0), (20.0, 22.5)])
    assert len(joined) / vad.RATE == pytest.approx(3.0 + vad.JOIN + 2.5)
    assert mapping(0.0) == 2.0 and mapping(1.25) == 3.25 and mapping(3.0) == 5.0
    after_join = 3.0 + vad.JOIN
    assert mapping(after_join) == pytest.approx(20.0) and mapping(after_join + 1.5) == pytest.approx(21.5)
    # Inside the joining silence a time goes to the nearer side, never into the gap.
    assert mapping(3.0 + 0.1) == 5.0 and mapping(after_join - 0.05) == pytest.approx(20.0)
    assert mapping(99.0) == 22.5


# ── the four clips: zero invented lines ─────────────────────────────────────

@needs_ffmpeg
def test_a_silent_clip_is_never_sent_and_has_no_lines(tmp_path):
    clip = video_with(tmp_path / "beach.mp4", audio_clip(tmp_path / "beach.wav", 8.0, HISS), 8.0)
    adapter = WhisperTranscriptionAdapter("sk-test", post=_never, post_diarize=_never)
    t = adapter.transcribe(_source(clip, 8.0))
    assert t.words == () and t.statements == ()
    assert adapter.diarize(_source(clip, 8.0)) == []


@needs_ffmpeg
def test_a_whatsapp_clip_sends_only_its_speech_and_keeps_its_times(tmp_path):
    """Speech from 1 s to 4 s, then 16 s of a quiet room: only the speech goes,
    the reply's times land back on the clip, and the sign-off Whisper invents
    on what little silence is sent is dropped."""
    expr = f"if(between(t,1,4),{SPEECH_LIKE},0)+{HISS}"
    clip = video_with(tmp_path / "wa.mp4", audio_clip(tmp_path / "wa.wav", 20.0, expr), 20.0)
    sent = {}

    def post(path, key, timeout):
        sent["seconds"] = _sent_seconds(path)
        # In the sent audio the voice starts ~0.3 s in (the span's padding).
        return {"language": "english",
                "segments": [_seg(" See you at eight.", 0.3, 3.3, no_speech_prob=0.02, avg_logprob=-0.2),
                             _seg(" Thanks for watching!", 3.35, 3.6, no_speech_prob=0.7, avg_logprob=-0.9)],
                "words": _words("See you at eight.", 0.3, 3.3) + _words("Thanks for watching!", 3.35, 3.6)}

    turns = {"segments": [{"speaker": "A", "start": 0.3, "end": 3.3, "text": " See you at eight."}]}
    t = WhisperTranscriptionAdapter("sk-test", post=post, post_diarize=lambda *a: turns).transcribe(_source(clip, 20.0))
    assert sent["seconds"] < 5.0                                     # not the 20 s clip
    assert [s.text for s in t.statements] == ["See you at eight."]
    [line] = t.statements
    spans = vad.speech_spans(vad.read_wav(ffmpeg.extract_audio(clip, tmp_path / "x.wav")[0]))
    assert line.start == pytest.approx(spans[0][0] + 0.3, abs=1 / vad.RATE)    # mapped back, to the sample
    assert 0.9 <= line.start <= 1.3 and 3.9 <= line.end <= 4.4
    assert {w.speaker for w in t.words} == {"A"}


@needs_ffmpeg
def test_a_music_only_clip_has_no_lines(tmp_path):
    """A loud bed is always sent (the detector never judges speech under
    music by level), so the screens after transcription do the work."""
    clip = video_with(tmp_path / "music.mp4", audio_clip(tmp_path / "music.wav", 10.0, MUSIC), 10.0)
    reply = {"language": "english",
             "segments": [_seg(" [Music]", 0.0, 3.0, no_speech_prob=0.1, avg_logprob=-0.3),
                          _seg(" ♪ ♪", 3.0, 6.0, no_speech_prob=0.1, avg_logprob=-0.3),
                          _seg(" Thank you.", 8.0, 9.0, no_speech_prob=0.1, avg_logprob=-0.3)],
             "words": _words("Music", 0.0, 3.0) + _words("Thank you.", 8.0, 9.0)}
    t = WhisperTranscriptionAdapter("sk-test", post=lambda *a: reply, post_diarize=_never).transcribe(_source(clip, 10.0))
    assert t.words == () and t.statements == ()


@needs_ffmpeg
def test_a_clip_with_no_audio_track_is_never_sent(tmp_path):
    """No audio track at all, through ingest's silent track (the upload path)."""
    from app.media import ingest
    bare = video_with(tmp_path / "bare.mp4", None, 4.0)
    with_sound = ingest.add_silent_audio(bare, "mp4", 4.0)
    t = WhisperTranscriptionAdapter("sk-test", post=_never, post_diarize=_never).transcribe(_source(with_sound, 4.0))
    assert t.words == () and t.statements == ()


# ── run 5 item 8's bug stays fixed: speech under a loud music bed ────────────

def _under_music(tmp_path, speech_db):
    """The voice from 1 s to 4 s, `speech_db` over (or under) the music by RMS
    (0.3 of MUSIC measures -23.7 dBFS, SPEECH_LIKE -17.5)."""
    gain = 10 ** ((speech_db - 6.2) / 20)
    expr = f"0.3*({MUSIC})+if(between(t,1,4),{gain:.4f}*{SPEECH_LIKE},0)"
    return video_with(tmp_path / "bed.mp4", audio_clip(tmp_path / "bed.wav", 8.0, expr), 8.0)


@needs_ffmpeg
@pytest.mark.parametrize("speech_db", [5, 0, -6, -12])
def test_speech_under_a_loud_music_bed_is_always_sent(tmp_path, speech_db):
    """The music is the floor here, so the detector must never leave the
    speech out, however quiet the voice is against the music."""
    sent = {}

    def post(path, key, timeout):
        sent["seconds"] = _sent_seconds(path)
        return {"segments": [], "words": []}

    WhisperTranscriptionAdapter("sk-test", post=post, post_diarize=_no_turns).transcribe(
        _source(_under_music(tmp_path, speech_db), 8.0))
    assert sent["seconds"] == pytest.approx(8.0, abs=0.05)          # the whole bed, untouched


@needs_ffmpeg
def test_speech_under_a_loud_music_bed_is_kept(tmp_path):
    """Run 5 item 8's music_loud case end to end: sent whole, and the silence
    screen after (item 8's fix, against what plays between the words) keeps it."""
    clip = _under_music(tmp_path, 5)
    sent = {}

    def post(path, key, timeout):
        sent["seconds"] = _sent_seconds(path)
        return {"language": "english",
                "segments": [_seg(" One two three.", 1.0, 4.0, no_speech_prob=0.05, avg_logprob=-0.3)],
                "words": [{"word": "One", "start": 1.0, "end": 1.7}, {"word": "two", "start": 2.0, "end": 2.7},
                          {"word": "three.", "start": 3.0, "end": 3.7}]}

    t = WhisperTranscriptionAdapter("sk-test", post=post, post_diarize=_no_turns).transcribe(_source(clip, 8.0))
    assert sent["seconds"] == pytest.approx(8.0, abs=0.05)
    assert [s.text for s in t.statements] == ["One two three."]


# ── what is screened after transcription ────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Thanks for watching!", "Thank you for watching.", "Please subscribe.", "Like and subscribe!",
    "Don't forget to subscribe!", "謝謝觀看", "谢谢观看!", "請訂閱", "ご視聴ありがとうございました",
    "시청해주셔서 감사합니다", "Gracias por ver.", "Спасибо за просмотр!", "Продолжение следует...",
    "Subtítulos realizados por la comunidad de Amara.org", "Untertitel der Amara.org-Community",
    "Sous-titres réalisés para la communauté d'Amara.org", "Music.", "Applause",
])
def test_known_inventions_in_any_language_go_with_a_little_doubt(text):
    assert doubtful(_seg(text, 0, 2, no_speech_prob=0.3)) is not None


@pytest.mark.parametrize("text", ["[Music]", "[MUSIC PLAYING]", "(upbeat music)", "♪", "♪ ♪", "♪♪♪", "♫ la la la ♫",
                                  "[音楽]", "【音乐】", "(música)", "[Applause]", "*sighs*", "...", "- -"])
def test_a_caption_for_a_sound_always_goes(text):
    # However sure Whisper is: it is never a line to edit.
    assert doubtful(_seg(text, 0, 2, no_speech_prob=0.01, avg_logprob=-0.1)) is not None


@pytest.mark.parametrize("text", ["Get 20% off today only.", "(and that is the point) we ship on Monday.",
                                  "Music is my life, she said."])
def test_real_lines_are_not_mistaken_for_captions(text):
    assert doubtful(_seg(text, 0, 2, no_speech_prob=0.05, avg_logprob=-0.2)) is None


def test_a_segment_whisper_says_is_not_speech_goes():
    assert doubtful(_seg("We open at nine.", 0, 2, no_speech_prob=0.85, avg_logprob=-0.4)).startswith("no_speech_prob")


def test_off_language_segments_need_confidence_and_length():
    english = _seg("We open at nine and close at six every day.", 0.0, 4.0, no_speech_prob=0.02, avg_logprob=-0.2)

    def kept(seg):
        return [s.text for s in to_transcript({"language": "english", "segments": [english, seg]}).statements]

    # Short and unsure: dropped.
    assert kept(_seg("你好", 5.0, 5.4, no_speech_prob=0.4, avg_logprob=-0.8)) == [english["text"]]
    # Short but sure: still too short to be real speech in another language.
    assert kept(_seg("你好", 5.0, 5.4, no_speech_prob=0.05, avg_logprob=-0.2)) == [english["text"]]
    # Long but unsure: dropped.
    assert kept(_seg("今天我们一起去市场买菜", 5.0, 8.0, no_speech_prob=0.4, avg_logprob=-0.9)) == [english["text"]]
    # Long and sure: real code-switching stays.
    assert kept(_seg("今天我们一起去市场买菜", 5.0, 8.0, no_speech_prob=0.05, avg_logprob=-0.2)) == [
        english["text"], "今天我们一起去市场买菜"]


def test_a_clip_that_says_nothing_but_a_sign_off_has_no_lines():
    sure = {"segments": [_seg(" Thank you.", 1.0, 2.0, no_speech_prob=0.05, avg_logprob=-0.2)],
            "words": _words("Thank you.", 1.0, 2.0)}
    assert to_transcript(sure).statements == () and to_transcript(sure).words == ()
    # Said among real lines, a confident "Thank you." stays.
    among = {"segments": [_seg(" Your order is ready.", 0.0, 1.0, no_speech_prob=0.05, avg_logprob=-0.2),
                          _seg(" Thank you.", 1.0, 2.0, no_speech_prob=0.05, avg_logprob=-0.2)]}
    assert [s.text for s in to_transcript(among).statements] == ["Your order is ready.", "Thank you."]
