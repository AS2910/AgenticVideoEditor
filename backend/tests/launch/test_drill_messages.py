"""Rehearsal item 4: what people read when a drill's fault hits them."""
import httpx
import anthropic
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import _turn_failure_sentence, app


def test_a_claude_timeout_or_outage_reads_as_a_sentence_without_vendor_text():
    # Run 5 item 1: the owner's words for anything on our side; never the SDK's text or the exception's.
    from app.failures import OUR_END, OUR_END_REPORTED
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    timeout = _turn_failure_sentence(anthropic.APITimeoutError(request=req))
    assert timeout == OUR_END and "anthropic.com" not in timeout
    busy = anthropic.InternalServerError("x", response=httpx.Response(500, request=req), body=None)
    assert _turn_failure_sentence(busy) == OUR_END
    assert _turn_failure_sentence(RuntimeError("boom")) == OUR_END_REPORTED
    assert _turn_failure_sentence(RuntimeError("boom"), spent_usd=0.0) == OUR_END


def test_the_database_restarting_answers_503_with_a_sentence():
    class OperationalError(Exception):
        pass
    OperationalError.__module__ = "psycopg"

    @app.get("/__drill_pg")
    def down():
        raise OperationalError("server closed the connection unexpectedly")
    try:
        got = TestClient(app, raise_server_exceptions=False).get("/__drill_pg")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__drill_pg"]
    assert got.status_code == 503 and got.headers["retry-after"] == "5"
    assert got.json()["detail"].startswith("Voltage could not reach its database")
