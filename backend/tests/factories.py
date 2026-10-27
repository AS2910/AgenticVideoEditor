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


# Run 5 item 4: something speech-like for the voice activity detector to hear
# (silence is never sent to be transcribed): a 140 Hz voice with formant-ish
# harmonics, its loudness rising and falling four times a second like syllables.
SPEECH_LIKE = ("0.3*(sin(2*PI*140*t)+0.5*sin(2*PI*700*t)+0.4*sin(2*PI*1400*t)+0.2*sin(2*PI*2800*t))"
               "*pow(0.5+0.5*sin(2*PI*4*t),2)")


def audio_clip(dest, seconds: float, expr: str, rate: int = 16000):
    """A mono WAV made by ffmpeg from an `aevalsrc` expression of `t`."""
    from pathlib import Path
    from app.media import ffmpeg
    dest = Path(dest)
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s={rate}:d={seconds:.3f}",
        "-ac", "1", "-c:a", "pcm_s16le", str(dest),
    ])
    return dest


def video_with(dest, audio, seconds: float):
    """A small MP4 of a solid colour carrying `audio` as its sound (or none)."""
    from pathlib import Path
    from app.media import ffmpeg
    dest = Path(dest)
    picture, _ = ffmpeg.generate_solid_video(dest.with_name(f"picture-{dest.name}"), seconds)
    if audio is None:
        return picture
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(picture), "-i", str(audio),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest),
    ])
    return dest


def voiced_video(dest, seconds: float):
    """A video whose sound is speech-like from start to end."""
    from pathlib import Path
    dest = Path(dest)
    return video_with(dest, audio_clip(dest.with_name(f"voice-{dest.stem}.wav"), seconds, SPEECH_LIKE), seconds)
