from app.domain.models import Source, Selection, EditPlan, ApprovedEdit
from app.render.renderer import render, RenderSegment

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=3.0)


def edit(edit_id, start, end):
    plan = EditPlan(Selection(start, end), "x", "speaker-1")
    return ApprovedEdit(edit_id, plan, "audio://x", f"frames://{edit_id}")


def test_no_edits_yields_single_original_segment():
    manifest = render(SOURCE, [])
    assert manifest.segments == (
        RenderSegment(0.0, 3.0, "original", "ad.mp4"),
    )


def test_edit_replaces_its_span_and_originals_fill_gaps():
    manifest = render(SOURCE, [edit("e1", 1.0, 2.0)])
    assert manifest.segments == (
        RenderSegment(0.0, 1.0, "original", "ad.mp4"),
        RenderSegment(1.0, 2.0, "edited", "frames://e1"),
        RenderSegment(2.0, 3.0, "original", "ad.mp4"),
    )


def test_edits_are_ordered_by_start_time():
    manifest = render(SOURCE, [edit("e2", 2.0, 2.5), edit("e1", 0.5, 1.0)])
    kinds = [(s.kind, s.ref) for s in manifest.segments]
    assert kinds == [
        ("original", "ad.mp4"),
        ("edited", "frames://e1"),
        ("original", "ad.mp4"),
        ("edited", "frames://e2"),
        ("original", "ad.mp4"),
    ]
