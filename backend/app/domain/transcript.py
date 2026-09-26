from dataclasses import replace
from typing import Sequence

from app.domain.models import Statement, Transcript, Selection

# Grouping words into statements when Whisper gave none (projects transcribed
# before Phase 10): a pause this long, this many words, or a change of speaker
# ends a statement.
_STATEMENT_GAP = 0.6
_STATEMENT_WORDS = 15


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _speaker_at(start: float, end: float, turns: Sequence[tuple[str, float, float]]) -> str | None:
    """The speaker whose turn overlaps [start, end] most; the nearest turn for
    a zero-length word (Whisper gives some)."""
    if not turns:
        return None
    best = max(turns, key=lambda t: _overlap(start, end, t[1], t[2]))
    if _overlap(start, end, best[1], best[2]) > 0:
        return best[0]
    mid = (start + end) / 2
    return min(turns, key=lambda t: min(abs(mid - t[1]), abs(mid - t[2])))[0]


def assign_speakers(transcript: Transcript, turns: Sequence[tuple[str, float, float]]) -> Transcript:
    """Label every word and statement with the speaker of the diarized turn
    (speaker, start, end) it overlaps most."""
    if not turns:
        return transcript
    words = tuple(replace(w, speaker=_speaker_at(w.start, w.end, turns)) for w in transcript.words)
    statements = tuple(
        replace(s, speaker=_speaker_at(s.start, s.end, turns)) for s in transcript.statements
    )
    return Transcript(words=words, statements=statements)


def speaker_of(transcript: Transcript, selection: Selection) -> str | None:
    """The one speaker whose words the selection covers; None when it covers
    no labelled speech, or more than one speaker."""
    speakers = {
        w.speaker for w in transcript.words
        if w.end > selection.start and w.start < selection.end
    }
    speakers.discard(None)
    return speakers.pop() if len(speakers) == 1 else None


def statements_of(transcript: Transcript) -> tuple[Statement, ...]:
    """The transcript's statements — Whisper's, or grouped from its words."""
    if transcript.statements:
        return transcript.statements
    groups: list[list] = []
    for word in transcript.words:
        if (not groups or word.start - groups[-1][-1].end >= _STATEMENT_GAP
                or len(groups[-1]) >= _STATEMENT_WORDS
                or word.speaker != groups[-1][-1].speaker):
            groups.append([word])
        else:
            groups[-1].append(word)
    return tuple(
        Statement(" ".join(w.text for w in g), g[0].start, g[-1].end, _majority(g)) for g in groups
    )


def _majority(words: list) -> str | None:
    labels = [w.speaker for w in words if w.speaker is not None]
    return max(set(labels), key=labels.count) if labels else None


def snap_to_word_boundaries(transcript: Transcript, selection: Selection) -> Selection:
    """Widen a selection outward to the nearest enclosing word boundaries.

    Ensures cuts land in natural silences between words rather than mid-syllable.
    """
    words = transcript.words
    if not words:
        return selection

    starts_at_or_before = [w.start for w in words if w.start <= selection.start]
    new_start = max(starts_at_or_before) if starts_at_or_before else words[0].start

    ends_at_or_after = [w.end for w in words if w.end >= selection.end]
    new_end = min(ends_at_or_after) if ends_at_or_after else words[-1].end

    # A selection that falls entirely outside the words can produce start > end;
    # collapse such degenerate selections to a single point.
    new_start = min(new_start, new_end)

    return Selection(start=new_start, end=new_end)
