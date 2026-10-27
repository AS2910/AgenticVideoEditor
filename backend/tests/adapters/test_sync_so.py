"""The sync.so client (Phase 17a). No network, no spend: httpx's mock transport
plays the vendor, with the response shapes read from the live API on 2026-10-14."""
import json

import httpx
import pytest

from app.adapters.base import VendorError
from app.adapters.sync_so import (
    MouthConfigError, MouthError, MouthRefused, SyncSoClient,
)
from app.errors import NonRetryableError

KEY = "sync_test_never_real_0123456789"


class Vendor:
    """A scripted sync.so: records every request, answers by route."""

    def __init__(self, statuses=("PENDING", "PROCESSING", "COMPLETED"), asset_id="asset-1", fail=None):
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses)
        self.asset_id = asset_id
        self.fail = fail or {}                              # (method, path) -> (status, body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = (request.method, request.url.path)
        if request.url.host == "cdn.sync.so":
            return httpx.Response(200, content=b"MOUTH-FRAMES")
        if route in self.fail:
            status, body = self.fail[route]
            return httpx.Response(status, text=body)
        if route == ("POST", "/v2/assets/upload"):
            return httpx.Response(201, json={"uploadUrl": "https://uploads.sync.so/put?sig=1", "url": "https://assets.sync.so/u/clip.mp4", "expiresIn": 3600})
        if request.method == "PUT":
            return httpx.Response(200)
        if route == ("POST", "/v2/assets"):
            return httpx.Response(201, json={"id": self.asset_id} if self.asset_id else {})
        if route == ("POST", "/v2/generate"):
            return httpx.Response(201, json={"id": "job-1", "status": "PENDING"})
        if route == ("GET", "/v2/generate/job-1"):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            body = {"id": "job-1", "status": status}
            if status == "COMPLETED":
                body |= {"outputUrl": "https://api.sync.so/out/job-1.mp4", "outputDuration": 1.2667}
            if status in ("FAILED", "REJECTED"):
                body |= {"error": "No face could be found in the video.", "errorCode": "no_face"}
            return httpx.Response(200, json=body)
        if route == ("GET", "/out/job-1.mp4"):
            return httpx.Response(302, headers={"location": "https://cdn.sync.so/out/job-1.mp4"})
        if route == ("POST", "/v2/generations/estimate"):
            return httpx.Response(200, json={"estimatedFrameCount": 300, "estimatedGenerationCost": 0.6, "estimatedCredits": None})
        return httpx.Response(404, text="not found")

    def client(self, **kw):
        return SyncSoClient(KEY, http=httpx.Client(transport=httpx.MockTransport(self)),
                            poll_every=0, sleep=lambda s: None, **kw)

    def body(self, method, path):
        return json.loads(next(r for r in self.requests if (r.method, r.url.path) == (method, path)).content)


@pytest.fixture()
def files(tmp_path):
    video, audio = tmp_path / "clip.mp4", tmp_path / "take.wav"
    video.write_bytes(b"V" * 100)
    audio.write_bytes(b"A" * 50)
    return video, audio


def test_a_local_file_goes_up_as_an_asset_and_is_referenced_by_its_id(files):
    vendor = Vendor()
    asset = vendor.client().upload(files[0], "video/mp4", "video")
    assert asset == {"assetId": "asset-1"}
    assert vendor.body("POST", "/v2/assets/upload") == {"fileName": "clip.mp4", "contentType": "video/mp4", "size": 100}
    put = next(r for r in vendor.requests if r.method == "PUT")
    assert put.content == b"V" * 100 and "x-api-key" not in put.headers            # storage gets the bytes, never the key
    assert vendor.body("POST", "/v2/assets") == {"url": "https://assets.sync.so/u/clip.mp4", "type": "VIDEO", "name": "clip.mp4"}


def test_an_asset_without_an_id_falls_back_to_its_url(files):
    assert Vendor(asset_id=None).client().upload(files[0], "video/mp4", "video") == {"url": "https://assets.sync.so/u/clip.mp4"}


def test_a_refused_upload_is_retryable(files):
    vendor = Vendor()
    real = vendor.__call__

    def refuse(request):
        return httpx.Response(403) if request.method == "PUT" else real(request)

    client = SyncSoClient(KEY, http=httpx.Client(transport=httpx.MockTransport(refuse)), sleep=lambda s: None)
    with pytest.raises(MouthError, match="refused the upload"):
        client.upload(files[0], "video/mp4", "video")


def test_a_job_is_polled_until_it_completes(files):
    vendor = Vendor()
    job = vendor.client().wait("job-1")
    assert job["status"] == "COMPLETED" and job["outputDuration"] == 1.2667
    assert sum(1 for r in vendor.requests if r.url.path == "/v2/generate/job-1") == 3


@pytest.mark.parametrize("status", ["FAILED", "REJECTED"])
def test_a_job_the_vendor_could_not_do_is_a_refusal_with_its_reason(status):
    with pytest.raises(MouthRefused, match="No face could be found") as err:
        Vendor(statuses=(status,)).client().wait("job-1")
    assert err.value.code == "no_face" and isinstance(err.value, NonRetryableError)


def test_a_job_that_never_finishes_gives_up_and_can_be_retried():
    ticks = iter(range(0, 10_000, 100))
    client = SyncSoClient(KEY, http=httpx.Client(transport=httpx.MockTransport(Vendor(statuses=("PROCESSING",)))),
                          poll_every=0, poll_for=300, sleep=lambda s: None, clock=lambda: next(ticks))
    with pytest.raises(MouthError, match="taking too long") as err:
        client.wait("job-1")
    assert isinstance(err.value, VendorError)


def test_the_result_is_downloaded_through_the_redirect(tmp_path):
    out = Vendor().client().download("https://api.sync.so/out/job-1.mp4", tmp_path / "out" / "mouth.mp4")
    assert out.read_bytes() == b"MOUTH-FRAMES"


def test_estimate_reads_the_price_and_says_none_when_it_cannot():
    assert Vendor().client().estimate("lipsync-2", 10) == 0.6
    broken = Vendor(fail={("POST", "/v2/generations/estimate"): (500, "oops")})
    assert broken.client().estimate("lipsync-2", 10) is None


def test_the_estimate_asks_for_the_model_and_the_length():
    vendor = Vendor()
    vendor.client().estimate("sync-3", 1.26)
    assert vendor.body("POST", "/v2/generations/estimate") == {"model": "sync-3", "duration": 1.26}


def test_the_whole_trip_video_and_audio_in_mouth_out(files, tmp_path):
    vendor = Vendor()
    out, job = vendor.client().move_mouth(*files[:1], files[1], tmp_path / "out.mp4", model="lipsync-2")
    assert out.read_bytes() == b"MOUTH-FRAMES" and job["status"] == "COMPLETED"
    body = vendor.body("POST", "/v2/generate")
    assert body["model"] == "lipsync-2"
    assert [i["type"] for i in body["input"]] == ["video", "audio"] and all("assetId" in i for i in body["input"])
    assert body["options"] == {"sync_mode": "cut_off"}


def test_options_are_passed_through_for_more_than_one_face(files, tmp_path):
    vendor = Vendor()
    vendor.client().move_mouth(files[0], files[1], tmp_path / "o.mp4", options={"active_speaker_detection": {"auto_detect": True}})
    assert vendor.body("POST", "/v2/generate")["options"] == {"sync_mode": "cut_off", "active_speaker_detection": {"auto_detect": True}}


@pytest.mark.parametrize("status, body, expect, kind", [
    (401, "Unauthorized", "rejected the API key", MouthConfigError),
    (402, "payment required", "no credit left", MouthConfigError),
    (400, '{"message":"Validation failed: duration"}', "Validation failed", MouthConfigError),
    (429, "slow down", "unavailable", MouthError),
    (503, "down", "unavailable", MouthError),
])
def test_vendor_failures_become_plain_sentences_of_the_right_kind(files, status, body, expect, kind):
    vendor = Vendor(fail={("POST", "/v2/generate"): (status, body)})
    with pytest.raises(kind, match=expect):
        vendor.client().generate({"model": "lipsync-2"})


def test_the_key_never_appears_in_an_error(files):
    vendor = Vendor(fail={("POST", "/v2/generate"): (400, f"bad request for {KEY}")})
    with pytest.raises(MouthConfigError) as err:
        vendor.client().generate({})
    assert KEY not in str(err.value)


def test_a_network_failure_is_retryable_and_does_not_echo_details():
    def boom(request):
        raise httpx.ConnectError(f"connection failed for {KEY}")

    client = SyncSoClient(KEY, http=httpx.Client(transport=httpx.MockTransport(boom)), sleep=lambda s: None)
    with pytest.raises(MouthError) as err:
        client.generate({})
    assert KEY not in str(err.value) and "ConnectError" in str(err.value)


def test_the_key_goes_to_the_api_and_nowhere_else(files):
    vendor = Vendor()
    vendor.client().move_mouth(files[0], files[1], files[0].parent / "o.mp4")
    api = [r for r in vendor.requests if r.url.path.startswith("/v2/")]
    assert api and all(r.headers["x-api-key"] == KEY for r in api)
    elsewhere = [r for r in vendor.requests if not r.url.path.startswith("/v2/")]
    assert elsewhere and all("x-api-key" not in r.headers for r in elsewhere)     # the storage PUT and the download
