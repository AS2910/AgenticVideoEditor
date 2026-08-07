from app.domain.models import Transcript, Selection


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
