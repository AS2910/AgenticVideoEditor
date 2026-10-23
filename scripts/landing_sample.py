"""Launch item 8: make the landing page's "after" video again.

Runs the sample ad's recorded tutorial edit (20% off -> 30% off; no vendor
is called, nothing is spent) through the app's own render in a throwaway
data folder, and copies the finished render to
frontend/public/sample-ad-after.mp4. The "before" is
frontend/public/sample-ad.mp4, the same file as the tutorial's sample.

    cd backend && PYTHONPATH="$PWD" .venv/bin/python ../scripts/landing_sample.py
"""
import glob
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "sample-ad-after.mp4"
data = tempfile.mkdtemp(prefix="ave-landing-")
os.environ.update(AVE_DATA_DIR=data, OPENAI_API_KEY="", ELEVENLABS_API_KEY="", ANTHROPIC_API_KEY="", AVE_DRY_RUN="",
                  DATABASE_URL="", AVE_EMAIL_PROVIDER="outbox", AVE_MEASURE="0", AVE_AUTH="off")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402


def main() -> int:
    client = TestClient(app)
    vid = client.post("/tutorial").json()["video_id"]

    def wait(job_id: str) -> dict:
        while True:
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] in ("succeeded", "failed"):
                return job
            time.sleep(0.1)

    wait(client.post(f"/videos/{vid}/turns", json={"text": "Make the offer 30% off"}).json()["job_id"])
    done = wait(client.post(f"/videos/{vid}/turns", json={"text": "Go ahead"}).json()["job_id"])
    candidate = done["result"]["plan"]["items"][0]["candidate"]["candidate_id"]
    client.post(f"/videos/{vid}/edits", json={"candidate_id": candidate}).raise_for_status()
    render = client.post(f"/videos/{vid}/export").json()["render"]
    [path] = glob.glob(f"{data}/**/{render['sha256']}*", recursive=True)
    shutil.copy(path, OUT)
    shutil.rmtree(data, ignore_errors=True)
    print(f"{OUT} ({render['duration']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
