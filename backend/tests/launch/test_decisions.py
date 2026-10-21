"""Launch item 0: the decisions from the projects-plan MORNING, section 3."""
from dataclasses import replace

from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app


def test_the_abuse_report_kind_is_only_offered_to_admins(monkeypatch):
    client = TestClient(app)
    kinds = [k["kind"] for k in client.get("/me/notifications/settings").json()["kinds"]]
    assert "abuse_report" in kinds                                    # local is an admin by default
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=()))
    kinds = [k["kind"] for k in client.get("/me/notifications/settings").json()["kinds"]]
    assert "abuse_report" not in kinds and "job_done" in kinds
    refused = client.put("/me/notifications/settings", json={"abuse_report": {"email": False}},
                         headers={"X-Requested-With": "voltage"})
    assert refused.status_code == 422
