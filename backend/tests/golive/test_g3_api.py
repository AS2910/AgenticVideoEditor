"""G3 through the API: opening Billing starts the free trial; details pick
the provider and currency; a plan and a top-up go through the fake provider
(test mode) and make invoices; the invoice page; credits used up stop paid
work in the spend guard with a sentence; 50/80/100% alerts in the bell once
each; "about N minutes" only once a cost per exported minute is measured;
flag off 404."""
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import analytics
from app.api.main import app, flags, jobs, ledger, repo
from app.billing import CreditsUsedUp
from app.media import ffmpeg
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("golive.g3", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def test_billing_starts_the_trial_and_buys_through_the_fake_provider(client):
    view = client.get("/billing").json()
    assert view["credits"]["granted"] == 5.0 and view["credits"]["left"] == 5.0 and view["plan"] is None
    assert view["credits"]["minutes"] is None                     # nothing exported yet: no minute figure
    assert view["provider"] == {"name": "stripe", "label": "Stripe (test mode)", "test_mode": True}
    india = client.put("/billing/details", json={"country": "IN", "legal_name": "Ash Films", "gstin": "29ABCDE1234F1Z5"}).json()
    assert india["provider"]["name"] == "razorpay" and india["account"]["state_code"] == "29"
    assert {p["plan_id"]: (p["price"], p["currency"]) for p in india["plans"]}["studio"] == (4999.0, "INR")
    assert client.put("/billing/details", json={"country": "IN", "gstin": "nope"}).status_code == 422
    plan = client.post("/billing/plan", json={"plan": "studio"})
    assert plan.status_code == 200, plan.text
    inv = plan.json()["invoice"]
    assert (inv["tax_kind"], inv["cgst"], inv["sgst"], inv["provider"]) == ("intra", 449.91, 449.91, "razorpay")
    assert plan.json()["credits"]["granted"] == 55.0 and plan.json()["plan"]["plan_id"] == "studio"
    top = client.post("/billing/topup", json={"credits": 10}).json()
    assert top["credits"]["granted"] == 65.0 and [i["kind"] for i in top["invoices"]] == ["topup", "plan"]
    page = client.get(f"/billing/invoices/{inv['id']}")
    assert page.status_code == 200 and "Tax invoice" in page.text and "Test mode" in page.text
    assert client.get("/billing/invoices/999").status_code == 404
    assert client.post("/billing/plan", json={"plan": "gold"}).status_code == 422


def test_credits_used_up_stop_paid_work_and_alerts_say_so_once(client, sample_video, monkeypatch):
    monkeypatch.setattr(ledger, "ceiling_usd", 100.0)              # only the credits run out here
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    main._ensure_spend("p1")                                         # no billing account yet: billing does not apply
    client.get("/billing")                                            # opening Billing starts the trial (5 credits)
    ledger.record("p1", "elevenlabs", "speech", 100, "characters", 2.6)
    ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.1)
    ledger.record("p1", "elevenlabs", "speech", 100, "characters", 1.5)
    main._ensure_spend("p1")                                         # 4.2 of 5 used: still fine
    ledger.record("p1", "elevenlabs", "speech", 100, "characters", 1.0)
    with pytest.raises(CreditsUsedUp, match="Your credits are used up"):
        main._ensure_spend("p1")
    titles = [n["title"] for n in client.get("/me/notifications").json()["items"] if n["link"] == "#billing"]
    assert titles == ["You have used all your credits. Paid steps are paused until you top up or pick a plan.",
                      "You have used 80% of your credits (4.20 of 5.00).", "You have used 50% of your credits (2.60 of 5.00)."]
    view = client.get("/billing").json()
    assert view["credits"]["left"] < 0
    client.post("/billing/topup", json={"credits": 10})               # a top-up and the work carries on
    main._ensure_spend("p1")


def test_about_n_minutes_only_once_measured(client, sample_video):
    client.get("/billing")
    analytics.track("video_exported", "local", {"seconds": 120})
    ledger.record("p0", "openai", "transcription", 1, "minutes", 1.0)
    view = client.get("/billing").json()
    per_minute = analytics.cost_per_exported_minute(main.database)["per_minute"]
    assert per_minute and view["credits"]["minutes"] == int(view["credits"]["left"] / per_minute)


def test_flag_off(client):
    flags.set("golive.g3", "local", False)
    assert client.get("/billing").status_code == 404
    assert client.post("/billing/topup", json={"credits": 10}).status_code == 404
