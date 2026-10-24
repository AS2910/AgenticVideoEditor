"""Builders for domain objects that tests need but are not testing.

Keeps the `Source(..., media=...)` boilerplate in one place, so adding a field
to a domain model does not mean editing every test file again.
"""
from app.domain.models import Source, MediaArtifact

SOURCE_MEDIA = MediaArtifact(
    kind="video", sha256="5" * 64, path="/tmp/source.mp4", duration=30.0, container="mp4",
)


def make_source(
    project_id: str = "p1",
    filename: str = "ad.mp4",
    duration: float = 30.0,
    media: MediaArtifact | None = None,
) -> Source:
    return Source(
        project_id=project_id,
        filename=filename,
        duration=duration,
        media=media or SOURCE_MEDIA,
    )


def media_get(client, path: str, owner: str = "local", **kwargs):
    """GET a media route the way the app does: with a signed media token (launch item 2)."""
    from app.api.main import mint_media_token
    token = mint_media_token(owner)["token"]
    return client.get(path + ("&" if "?" in path else "?") + "mt=" + token, **kwargs)


def export_now(client, url, **kw):
    """Run 4, item 3d: POST <video>/export never renders; a render not made yet answers 202
    with its job. This follows the job and asks again, so a test reads the render as the
    route used to answer it (any other answer comes back as it is)."""
    import time
    video = url.split("/")[2]
    deadline = time.time() + 180
    while True:
        resp = client.post(url, **kw)
        if resp.status_code != 202:
            return resp
        job_id = resp.json()["render_job"]["job_id"]
        found = None
        while time.time() < deadline:
            found = next((j for j in client.get(f"/videos/{video}/jobs").json()["jobs"] if j["job_id"] == job_id), None)
            if found and found["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.02)
        assert found and found["status"] == "done", found
