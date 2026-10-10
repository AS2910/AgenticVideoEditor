"""Picture that flexes (Phase 16): the pieces of the output."""
import math

import pytest

from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection, Transcript, Word
from app.render import retime
from app.render.renderer import RenderInsert

AUDIO = MediaArtifact("audio", "a" * 64, "/nonexistent.wav", 0.8, "wav")
WORDS = Transcript(words=(Word("one", 0.5, 1.0), Word("two", 1.6, 2.1), Word("three", 2.1, 2.6)))


def edit(start, end, mix="replace", flex=None, duration=0.8):
    audio = MediaArtifact("audio", "b" * 64, "/nonexistent.wav", duration, "wav")
    return ApprovedEdit("e1", "c1", EditPlan(Selection(start, end), "x", "v", mix=mix, flex=flex), audio, audio)


def insert(at, duration=0.8):
    return RenderInsert(at, duration, edit(at - 0.5, at, "concatenate", duration=duration))


# ── allocate ──────────────────────────────────────────────────────────────────

def test_extra_time_goes_where_the_picture_moves_least():
    chunks = retime.allocate(0.0, 1.0, 0.3, [10, 1, 1, 10], 1.6)
    assert [round(c.factor, 2) for c in chunks] == [1.05, 1.55, 1.55, 1.05]
    assert sum((c.end - c.start) * c.factor for c in chunks) == pytest.approx(1.3)


def test_no_chunk_passes_the_limit_and_the_rest_is_left_out():
    chunks = retime.allocate(0.0, 1.0, 2.0, [1, 1, 1, 1], 1.6)
    assert all(c.factor <= 1.6 + 1e-9 for c in chunks)
    assert sum((c.end - c.start) * c.factor for c in chunks) == pytest.approx(1.6)


def test_a_squeeze_is_shared_the_same_way_and_bounded():
    chunks = retime.allocate(0.0, 1.0, -0.1, [1, 1], 1.12)
    assert [round(c.factor, 3) for c in chunks] == [0.9, 0.9]
    tight = retime.allocate(0.0, 1.0, -0.5, [1, 1], 1.12)
    assert all(c.factor >= 1 / 1.12 - 1e-9 for c in tight)


# ── flex ──────────────────────────────────────────────────────────────────────

def test_a_flexed_line_becomes_a_piece_the_length_of_its_take():
    e = edit(1.0, 2.0, flex=1.1, duration=1.1)
    [p] = retime.flex_pieces([e])
    assert (p.kind, p.start, p.end, p.out, p.edit) == ("flex", 1.0, 2.0, 1.1, e)
    assert p.factor == 1.1
    assert sum((c.end - c.start) * c.factor for c in p.chunks) == pytest.approx(1.1)


def test_lines_without_flex_or_reverted_make_no_piece():
    plain = edit(1.0, 2.0)
    undone = ApprovedEdit("e2", "c2", EditPlan(Selection(1, 2), "x", "v", flex=1.1), AUDIO, AUDIO, reverted=True)
    assert retime.flex_pieces([plain, undone]) == []


# ── living holds ──────────────────────────────────────────────────────────────

def test_an_added_line_stretches_the_pause_after_it():
    # The pause after "one" runs 1.0 → 1.6 (0.6 s); a 0.8 s line fits in one pass at 1.6×? 0.6 × 1.6 = 0.96 < 1.4: no.
    [p] = retime.living_pieces([insert(1.0, 0.3)], WORDS, 3.0)
    assert (p.kind, p.start, p.end, p.loops, p.line_first) == ("living", 1.0, 1.6, 1, True)
    assert p.out == pytest.approx(0.9)
    assert max(c.factor for c in p.chunks) <= 1.6 + 1e-9


def test_a_long_line_loops_the_stretched_pause_instead_of_freezing():
    [p] = retime.living_pieces([insert(1.0, 0.8)], WORDS, 3.0)
    assert p.kind == "living" and p.out == pytest.approx(1.4)
    assert p.loops == math.ceil(1.4 / (0.6 * 1.6)) == 2
    assert p.held == 0.0


def test_the_window_never_crosses_a_cut():
    [p] = retime.living_pieces([insert(1.0, 0.3)], WORDS, 3.0, cuts=[1.3])
    assert (p.start, p.end) == (1.0, 1.3)


def test_with_no_pause_the_tail_of_the_line_is_the_window():
    # "two" ends at 2.1 and "three" starts there: no pause. The window is the 0.4 s before.
    [p] = retime.living_pieces([insert(2.1, 0.5)], WORDS, 3.0)
    assert (p.kind, p.start, p.end, p.line_first) == ("living", pytest.approx(1.7), 2.1, False)
    assert p.out == pytest.approx(0.9)


def test_only_a_window_too_short_to_stretch_is_held_and_says_so():
    [p] = retime.living_pieces([insert(0.05, 0.5)], Transcript(words=(Word("x", 0.05, 0.4),)), 3.0)
    assert (p.kind, p.start, p.end, p.out, p.held) == ("hold", 0.05, 0.05, 0.5, 0.5)


def test_a_window_already_taken_by_a_flexed_line_falls_back_to_a_hold():
    [p] = retime.living_pieces([insert(2.1, 0.5)], WORDS, 3.0, taken=[(1.6, 2.1)])
    assert p.kind == "hold"


def test_plain_holds_are_the_old_behaviour():
    [p] = retime.plain_holds([insert(1.0, 0.8)], 3.0)
    assert (p.kind, p.start, p.end, p.out) == ("hold", 1.0, 1.0, 0.8)


# ── tiling and placing ────────────────────────────────────────────────────────

def test_pieces_tile_the_source_with_copies_between_on_the_frame_grid():
    e = edit(1.0, 2.0, flex=1.1, duration=1.1)
    [flex] = retime.flex_pieces([e])
    [living] = retime.living_pieces([insert(2.3, 0.3)], Transcript(words=(Word("a", 2.0, 2.3), Word("b", 2.7, 2.9))), 3.0)
    pieces = retime.tile(3.0, [flex, living], 25.0)
    assert [p.kind for p in pieces] == ["copy", "flex", "copy", "living", "copy"]
    assert pieces[0].end == pieces[1].start and pieces[-1].end == 3.0
    for p in pieces:
        assert abs(p.out * 25 - round(p.out * 25)) < 1e-6   # whole frames
    placed = retime.place(pieces)
    assert placed[0].out_start == 0.0
    assert placed[-1].out_end == pytest.approx(sum(p.out for p in pieces))
    assert placed[-1].out_end == pytest.approx(3.0 + 0.1 + 0.3, abs=1 / 25)


def test_overlapping_pieces_are_refused():
    a = retime.Piece(1.0, 2.0, 1.1, "flex")
    b = retime.Piece(1.5, 2.5, 1.0, "living")
    with pytest.raises(ValueError):
        retime.tile(3.0, [a, b], 25.0)


def test_the_manifest_and_render_time_follow_the_pieces():
    pieces = retime.tile(3.0, [retime.Piece(1.0, 2.0, 1.2, "flex", (retime.Chunk(1.0, 2.0, 1.2),))], 25.0)
    m = retime.manifest(pieces)
    assert [x["kind"] for x in m] == ["copy", "flex", "copy"]
    assert m[1] == {"start": 1.0, "end": 2.0, "out_start": 1.0, "out_end": 2.2, "kind": "flex", "factor": 1.2}
    assert retime.render_time(0.5, pieces) == 0.5
    assert retime.render_time(1.5, pieces) == pytest.approx(1.6)
    assert retime.render_time(2.5, pieces) == pytest.approx(2.7)
    assert retime.held_seconds(pieces) == 0.0
