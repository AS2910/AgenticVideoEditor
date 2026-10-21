"""Launch item 8: the worker process. One pass sends the due digests and,
once a day (never on the first pass), runs the purge; each behind its switch."""
from datetime import timedelta

from app.config import Settings
from app.notify import digest as digest_mod
from app.notify import email as email_mod
from app.worker import Worker, build, main as worker_main, run


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_a_pass_sends_digests_and_purges_only_once_a_day_has_passed():
    calls: list[str] = []
    clock = Clock()
    w = Worker(digests=lambda: calls.append("digests") or ["one"], purge=lambda: calls.append("purge"),
               purge_every=100, clock=clock)
    assert w.tick() == {"digests": 1}
    assert calls == ["digests"]                      # a restart never purges at once
    clock.t += 99
    w.tick()
    assert calls.count("purge") == 0
    clock.t += 1
    assert w.tick() == {"digests": 1, "purge": "done"}
    clock.t += 50
    w.tick()
    assert calls.count("purge") == 1 and calls.count("digests") == 4


def test_switched_off_tasks_are_not_called_and_a_failure_does_not_stop_the_other():
    assert Worker().tick() == {}
    clock = Clock()
    purged: list[int] = []

    def broken() -> list:
        raise RuntimeError("smtp down")

    w = Worker(digests=broken, purge=lambda: purged.append(1), purge_every=0, clock=clock)
    w.tick()
    assert w.tick() == {"digests": "failed", "purge": "done"}
    assert purged == [1]


def test_run_stops_when_told():
    import threading
    stop = threading.Event()
    seen: list[int] = []

    def digests() -> list:
        seen.append(1)
        stop.set()
        return []

    run(Worker(digests=digests), every=0.01, stop=stop)
    assert seen == [1]


def test_build_follows_the_switches(tmp_path):
    off = build(Settings(openai_api_key=None, data_dir=tmp_path), environ={})
    assert off.digests is None and off.purge is None
    on = build(Settings(openai_api_key=None, data_dir=tmp_path, purge_daily=True, dry_run=True),
               environ={"AVE_WORKER_DIGESTS": "1"})
    assert on.digests is not None and on.purge is not None
    assert on.purge().dry_run is False                 # the real purge, on an empty Bin
    assert on.digests() == []


def test_built_digests_send_what_is_due(tmp_path):
    from app.store.db import Database
    w = build(Settings(openai_api_key=None, data_dir=tmp_path, notify_owner_email="me@example.com"),
              environ={"AVE_WORKER_DIGESTS": "yes"})
    db = Database(tmp_path / "ave.db")
    old = digest_mod.utcnow() - timedelta(minutes=11)
    with db.tx() as c:
        digest_mod.queue_in(c, "local", "comment", project_id="p1", payload={"text": "Lovely"},
                            at=old.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    sent = w.digests()
    assert len(sent) == 1 and sent[0].to == "me@example.com"
    assert [e["kind"] for e in email_mod.outbox(db)] == ["digest"]


def test_once_runs_one_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AVE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AVE_PURGE_DAILY", raising=False)
    monkeypatch.delenv("AVE_WORKER_DIGESTS", raising=False)
    assert worker_main(["--once"]) == 0
    assert capsys.readouterr().out.strip() == "{}"
