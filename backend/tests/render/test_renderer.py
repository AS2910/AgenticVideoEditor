from app.domain.models import Selection, EditPlan, ApprovedEdit, MediaArtifact
from app.render.renderer import render, RenderSegment
from tests.factories import make_source, SOURCE_MEDIA

SOURCE = make_source(duration=3.0)

AUDIO = MediaArtifact(
    kind="audio", sha256="a" * 64, path="/tmp/a.wav", duration=1.0, container="wav",
)


def frames_for(edit_id: str) -> MediaArtifact:
    # A distinct content address per edit, without touching ffmpeg.
    return MediaArtifact(
        kind="video", sha256=edit_id * 8, path=f"/tmp/{edit_id}.mp4",
        duration=1.0, container="mp4",
    )


def edit(edit_id, start, end) -> ApprovedEdit:
    plan = EditPlan(Selection(start, end), "x", "speaker-1")
    return ApprovedEdit(edit_id, f"c-{edit_id}", plan, AUDIO, frames_for(edit_id))


def test_no_edits_yields_single_original_segment():
    manifest = render(SOURCE, [])
    assert manifest.segments == (
        RenderSegment(0.0, 3.0, "original", "ad.mp4", SOURCE_MEDIA),
    )


def test_edit_replaces_its_span_and_originals_fill_gaps():
    e1 = edit("e1", 1.0, 2.0)
    manifest = render(SOURCE, [e1])
    assert manifest.segments == (
        RenderSegment(0.0, 1.0, "original", "ad.mp4", SOURCE_MEDIA),
        RenderSegment(1.0, 2.0, "edited", e1.frames.sha256, e1.frames, e1),
        RenderSegment(2.0, 3.0, "original", "ad.mp4", SOURCE_MEDIA),
    )


def test_edits_are_ordered_by_start_time():
    manifest = render(SOURCE, [edit("e2", 2.0, 2.5), edit("e1", 0.5, 1.0)])
    kinds = [(s.kind, s.ref) for s in manifest.segments]
    assert kinds == [
        ("original", "ad.mp4"),
        ("edited", frames_for("e1").sha256),
        ("original", "ad.mp4"),
        ("edited", frames_for("e2").sha256),
        ("original", "ad.mp4"),
    ]


def test_every_segment_resolves_to_real_media():
    # Phase 7 composites straight off this manifest, so each span has to name
    # the artifact it comes from — the source for originals, frames for edits.
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0)])
    by_kind = {s.kind: s for s in manifest.segments}
    assert by_kind["edited"].artifact == frames_for("e1")
    assert by_kind["original"].artifact == SOURCE_MEDIA


# ── overlapping edits: the later approval wins (Phase 7) ─────────────────────

def edited(manifest):
    return [(s.start, s.end, s.edit.edit_id) for s in manifest.segments if s.kind == "edited"]


def test_re_approving_the_same_span_replaces_the_earlier_edit():
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0), edit("e2", 1.0, 2.0)])
    assert edited(manifest) == [(1.0, 2.0, "e2")]


def test_a_later_partial_overlap_trims_the_earlier_edit():
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0), edit("e2", 1.5, 2.5)])
    assert edited(manifest) == [(1.0, 1.5, "e1"), (1.5, 2.5, "e2")]


def test_a_later_edit_inside_an_earlier_one_splits_it():
    manifest = render(SOURCE, [edit("e1", 0.5, 2.5), edit("e2", 1.0, 1.5)])
    assert edited(manifest) == [(0.5, 1.0, "e1"), (1.0, 1.5, "e2"), (1.5, 2.5, "e1")]


def test_an_earlier_approval_never_overrides_a_later_one():
    # Approval order, not start time, decides who owns the overlap.
    manifest = render(SOURCE, [edit("e1", 1.5, 2.5), edit("e2", 1.0, 2.0)])
    assert edited(manifest) == [(1.0, 2.0, "e2"), (2.0, 2.5, "e1")]


def test_segments_tile_the_source_exactly():
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0), edit("e2", 1.5, 2.5), edit("e3", 0.2, 0.4)])
    spans = [(s.start, s.end) for s in manifest.segments]
    assert spans[0][0] == 0.0 and spans[-1][1] == 3.0
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert end == start


def test_edited_segments_carry_their_edit_for_the_audio():
    e1 = edit("e1", 1.0, 2.0)
    segment = next(s for s in render(SOURCE, [e1]).segments if s.kind == "edited")
    assert segment.edit is e1
