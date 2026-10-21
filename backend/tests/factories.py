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
