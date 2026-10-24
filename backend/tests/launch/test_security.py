"""Launch item 2: security. Media only through signed, expiring URLs."""
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, jobs, repo
from tests.api.test_endpoints import upload


def setup_function():
    repo.reset()
    jobs.reset()


def test_media_needs_a_signed_unexpired_token_for_its_owner(sample_video):
    client = TestClient(app)
    made = upload(client, sample_video).json()
    sha = made["media"]["sha256"]
    path = f"/videos/{made['video_id']}/artifacts/{sha}"
    assert client.get(path).status_code == 403                                 # the cookie alone is not enough
    good = main.mint_media_token("local")
    assert client.get(path, params={"mt": good["token"]}).status_code == 200
    assert client.get(path, params={"mt": good["token"] + "x"}).status_code == 403
    old = main.mint_media_token("local", now=0)
    refused = client.get(path, params={"mt": old["token"]})
    assert refused.status_code == 403 and "expired" in refused.json()["detail"]
    other = main.mint_media_token("google:someone")
    assert client.get(path, params={"mt": other["token"]}).status_code == 404  # not theirs
    # Share links are not media tokens.
    assert client.get(path, params={"mt": main.auth.sign({"k": "share", "o": "local"}, main.share_key)}).status_code == 403


def test_the_app_gets_a_token_that_expires():
    got = TestClient(app).get("/me/media-token").json()
    assert got["expires_in"] == main.MEDIA_SECONDS and got["token"] and got["expires_at"].endswith("Z")


def test_turns_uploads_and_sign_in_are_rate_limited_per_person(monkeypatch):
    from app.ratelimit import Limits
    clock = [0.0]
    limits = Limits(clock=lambda: clock[0])
    monkeypatch.setattr(main, "rate_limits", limits)
    for _ in range(30):
        assert limits.check("POST", "/api/videos/p1/turns", "google:a", "1.2.3.4") is None
    assert limits.check("POST", "/api/videos/p1/turns", "google:a", "1.2.3.4") == "turns"
    assert limits.check("POST", "/videos/p9/turns", "google:b", "1.2.3.4") is None        # per person, not per address
    assert limits.check("GET", "/videos/p1/messages", "google:a", "1.2.3.4") is None       # reads are not limited
    clock[0] += 601
    assert limits.check("POST", "/videos/p1/turns", "google:a", "1.2.3.4") is None        # the window passed
    for _ in range(20):
        limits.check("POST", "/auth/email", None, "9.9.9.9", "ann@example.com")
    assert limits.check("POST", "/auth/email", None, "9.9.9.9", "ann@example.com") == "auth"   # sign-in: account and address
    assert limits.check("POST", "/auth/email", None, "9.9.9.9", "bob@example.com") is None


def test_a_limited_request_answers_429_with_a_sentence(monkeypatch):
    monkeypatch.setenv("AVE_RATE_IMPORTS", "1/60")
    from app.ratelimit import Limits
    monkeypatch.setattr(main, "rate_limits", Limits())
    client = TestClient(app)
    client.post("/imports", json={"url": "https://example.invalid/a.mp4"})
    over = client.post("/imports", json={"url": "https://example.invalid/a.mp4"})
    assert over.status_code == 429 and over.headers["retry-after"] == "60"
    assert over.json()["detail"] == "That is a lot of imports in a short time. Try again in 1 minute."


def test_every_bucket_names_a_real_route():
    import re
    from app.ratelimit import BUCKETS
    from tests.launch.test_isolation import _all_routes
    paths = [re.sub(r"{\w+(:\w+)?}", "x", r.path) for r in _all_routes()]
    for name, (_methods, pattern, *_rest) in BUCKETS.items():
        if name in ("auth", "auth_ip"):
            continue                                   # covers sign-in routes added in item 5 too
        assert any(re.match(pattern, p) for p in paths), name


def test_an_unexpected_error_answers_one_sentence_and_no_trace(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /Users/x/.env and a key sk-123")
    monkeypatch.setattr(main.repo, "list", boom)
    resp = TestClient(app, raise_server_exceptions=False).get("/videos")
    assert resp.status_code == 500 and resp.json() == {"detail": main.SERVER_FAULT}
    assert "Traceback" not in resp.text and "sk-123" not in resp.text


def test_cors_allows_only_voltages_own_address():
    client = TestClient(app)
    ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    evil = client.options("/videos", headers={"Origin": "https://evil.example", **ask})
    assert "access-control-allow-origin" not in evil.headers
    own = client.options("/videos", headers={"Origin": main.settings.cors_origins[0], **ask})
    assert own.headers["access-control-allow-origin"] == main.settings.cors_origins[0]
    assert own.headers["access-control-allow-credentials"] == "true"


def test_responses_carry_the_security_headers():
    resp = TestClient(app).get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["x-frame-options"] == "DENY"


def test_production_refuses_to_start_without_its_secrets():
    from app.config import production_problems
    problems = production_problems({"AVE_AUTH": "off", "AVE_PUBLIC_URL": "http://voltage.example", "AVE_SESSION_SECRET": "short"})
    text = " ".join(problems)
    for needle in ("ANTHROPIC_API_KEY is missing", "AVE_SHARE_SECRET is missing", "must be an https://",
                   "AVE_SESSION_SECRET is too short", "AVE_AUTH is off"):
        assert needle in text
    ready = {"AVE_SESSION_SECRET": "s" * 40, "AVE_SHARE_SECRET": "k" * 40, "AVE_PUBLIC_URL": "https://voltage.example",
             "ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e", "OPENAI_API_KEY": "o", "AVE_EMAIL_PROVIDER": "resend",
             "AVE_AUTH": "google"}
    assert production_problems(ready) == []


def test_production_never_reads_the_dotenv_file(monkeypatch, tmp_path):
    from app import config
    called = []
    monkeypatch.setattr(config, "load_dotenv", lambda *a: called.append(1))
    monkeypatch.setenv("AVE_ENV", "production")
    settings = config.load_settings()
    assert settings.production and called == []
    with __import__("pytest").raises(RuntimeError, match="will not start in production"):
        config.ensure_production_ready(settings)
