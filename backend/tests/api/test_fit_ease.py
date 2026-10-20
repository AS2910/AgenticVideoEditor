"""A line that ran long (p61): its take was kept with the picture eased, and
"Let the picture ease" puts it on the line without voicing or paying again."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.domain.models import Selection
from app.domain.plan import Plan, PlanItem
from app.media import ffmpeg
from tests.api.test_endpoints import upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def _failed(eased: str | None) -> Plan:
    failure = {"reason": "too_long", "needs": 2.6, "has": 1.5, "tried": ["trimmed the take's pauses"], "syllables": 9, "budget": 5,
               "cost_usd": 0.03, "text": "Red stalks him now, gloves up high.", "eased_candidate_id": eased, "ease_s": 0.4 if eased else None}
    item = PlanItem(item_id="i1", selection=Selection(0.5, 2.0), old_text="", new_text=failure["text"], mix="layer", status="failed",
                    error="Too long for its gap: needs 2.6 s, has 1.5 s.", fit_failure=failure)
    return Plan(plan_id="plan9", project_id="p1", goal="", summary="", items=(item,), created_at="2026-10-20T00:00:00+00:00")


def test_let_the_picture_ease_uses_the_take_already_voiced_and_pays_nothing(client, sample_video):
    import app.api.main as main
    assert upload(client, sample_video).status_code == 200
    record = repo.get("p1")
    main._generate("p1", record, "c7", Selection(0.5, 2.0), "Red stalks him now, gloves up high.", "speaker-1", None, "layer",
                   lambda p, s: None, flex_max=1.25)
    repo.save_plan(_failed("c7"))
    before = main.ledger.spent_usd("p1")
    plan = client.get("/videos/p1/plans/plan9").json()
    assert plan["items"][0]["fit_failure"]["eased_candidate_id"] == "c7"        # the row knows the take is there
    out = client.post("/videos/p1/plans/plan9/items/i1/ease")
    assert out.status_code == 200
    item = out.json()["items"][0]
    assert item["status"] == "ready" and item["candidate"]["candidate_id"] == "c7"
    assert item["fit_failure"] is None and item["error"] is None
    assert item["note"] == "The picture eases 0.4 s so this take fits."
    assert main.ledger.spent_usd("p1") == before


def test_with_no_kept_take_the_picture_cannot_ease_from_the_row(client, sample_video):
    assert upload(client, sample_video).status_code == 200
    repo.save_plan(_failed(None))
    out = client.post("/videos/p1/plans/plan9/items/i1/ease")
    assert out.status_code == 409 and out.json()["detail"].startswith("There is no voiced take to ease in for this line.")
    assert client.post("/videos/p1/plans/plan9/items/nope/ease").status_code == 404
