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


# --- Phase 10: statements -----------------------------------------------------

from app.domain.models import Statement  # noqa: E402
from app.domain.transcript import statements_of  # noqa: E402


def test_whispers_statements_are_used_when_present():
    t = Transcript(words=(Word("hi", 0.0, 0.3),), statements=(Statement("Hi!", 0.0, 0.3),))
    assert statements_of(t) == (Statement("Hi!", 0.0, 0.3),)


def test_without_statements_words_are_grouped_at_pauses():
    t = Transcript(words=(
        Word("Hi", 0.0, 0.3), Word("there", 0.35, 0.7),
        Word("Done", 1.5, 1.8), Word("sir", 1.85, 2.0),
    ))
    assert statements_of(t) == (Statement("Hi there", 0.0, 0.7), Statement("Done sir", 1.5, 2.0))


def test_long_runs_are_split():
    words = tuple(Word(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(20))
    assert [len(s.text.split()) for s in statements_of(Transcript(words=words))] == [15, 5]
