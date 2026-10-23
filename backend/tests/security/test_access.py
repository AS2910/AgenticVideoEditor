"""Launch item 5: the live channel (SSE) follows the roles.
`/videos/{id}/events` answers its owner and the workspace's Editor; a
Reviewer only for a video shared with them; anyone else 404; nobody signed
in 401."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.main as main
from tests.launch.test_roles import _client, team  # noqa: F401 - the module fixture

H = {"X-Requested-With": "voltage"}


def test_the_live_channel_follows_the_roles(team, monkeypatch):  # noqa: F811
    # One opening event, so a stream that is allowed ends after it (limit=1).
    monkeypatch.setattr(main, "_jobs_view", lambda video_id, *a: {"jobs": [{"job_id": "j", "video_id": video_id}], "turn": None})
    ids = team["ids"]
    for who in ("ann", "ed"):
        got = team[who].get(f"/videos/{ids['video']}/events", params={"limit": 1})
        assert got.status_code == 200 and got.headers["content-type"].startswith("text/event-stream"), who
    rae = team["rae"]
    assert rae.get(f"/videos/{ids['video']}/events", params={"limit": 1}).status_code == 200      # shared with her
    assert rae.get(f"/videos/{ids['spare']}/events", params={"limit": 1}).status_code == 404      # not shared
    stranger = _client("zed")
    assert stranger.get(f"/videos/{ids['video']}/events", params={"limit": 1}).status_code == 404
    assert TestClient(main.app).get(f"/videos/{ids['video']}/events", params={"limit": 1}).status_code == 401
