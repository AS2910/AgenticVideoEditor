from app.domain.models import Word, Transcript, Selection
from app.domain.transcript import snap_to_word_boundaries

TRANSCRIPT = Transcript(words=(
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
))


def test_snaps_outward_to_cover_selection():
    # selection lands mid-word on both ends
    snapped = snap_to_word_boundaries(TRANSCRIPT, Selection(0.5, 1.0))
    assert snapped == Selection(0.4, 1.3)  # start of "20%" to end of "off"


def test_selection_on_exact_boundaries_is_unchanged():
    snapped = snap_to_word_boundaries(TRANSCRIPT, Selection(0.4, 1.3))
    assert snapped == Selection(0.4, 1.3)


def test_empty_transcript_returns_selection_unchanged():
    snapped = snap_to_word_boundaries(Transcript(words=()), Selection(0.5, 1.0))
    assert snapped == Selection(0.5, 1.0)


def test_selection_entirely_after_words_does_not_invert():
    snapped = snap_to_word_boundaries(TRANSCRIPT, Selection(2.5, 3.0))
    assert snapped.start <= snapped.end
