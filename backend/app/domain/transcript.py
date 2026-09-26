from app.domain.models import Statement, Transcript, Selection

# Grouping words into statements when Whisper gave none (projects transcribed
# before Phase 10): a pause this long, or this many words, ends a statement.
_STATEMENT_GAP = 0.6
_STATEMENT_WORDS = 15


def statements_of(transcript: Transcript) -> tuple[Statement, ...]:
    """The transcript's statements — Whisper's, or grouped from its words."""
    if transcript.statements:
        return transcript.statements
    groups: list[list] = []
    for word in transcript.words:
        if (not groups or word.start - groups[-1][-1].end >= _STATEMENT_GAP
                or len(groups[-1]) >= _STATEMENT_WORDS):
            groups.append([word])
        else:
            groups[-1].append(word)
    return tuple(
        Statement(" ".join(w.text for w in g), g[0].start, g[-1].end) for g in groups
    )


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
