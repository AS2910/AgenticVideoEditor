"""Rehearsal item 3 (the load test): an upload's slow steps (probe, store,
transcription) run off the event loop, so one upload never stalls every
other request. Before the fix, /health waited for the whole transcription."""
import threading
import time

from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app

H = {"X-Requested-With": "voltage"}


def test_other_requests_answer_while_an_upload_transcribes(monkeypatch, sample_video):
    real = main.transcriber.transcribe

    def slow(source):
        time.sleep(3)
        return real(source)
    monkeypatch.setattr(main.transcriber, "transcribe", slow)
    with TestClient(app) as client:
        done = {}

        def upload():
            with open(sample_video, "rb") as f:
                done["status"] = client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")},
                                             data={"consent": "true"}, headers=H).status_code
        t = threading.Thread(target=upload)
        t.start()
        time.sleep(1.0)                                   # the upload is inside its transcription now
        started = time.time()
        assert client.get("/health").status_code == 200
        waited = time.time() - started
        t.join()
    assert done["status"] == 200
    assert waited < 1.5, f"/health waited {waited:.1f} s behind an upload"
