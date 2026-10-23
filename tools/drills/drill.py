"""Failure drills against a rehearsal stack (rehearsal item 4). Results: OPS.md.

    python3 tools/drills/drill.py <drill> [--port 8090] [--name voltage-load]

Drills:
  kill-api       kill the API process (the job worker) while a line is being voiced
  kill-worker    kill the maintenance worker container
  restart-pg     restart Postgres while the app is serving
  vendor-500     ElevenLabs answers 500 on every call
  vendor-hang    ElevenLabs hangs past its timeout; Claude hangs too
  disk-95        fill the data disk to 95%, then free it

After each fault the same four things are asserted:
  1. no job stuck: nothing queued or running once the dust settles
  2. no double charge: the voice characters billed equal the takes that exist
  3. the user sees a clear status: a failed job carries one sentence, never a trace
  4. recovery without manual steps: the same go-ahead then works
Uses only the standard library; reads the dev outbox and the ledger through
scripts/rehearsal.sh sql.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "frontend" / "public" / "sample-ad.mp4"
TRACE_WORDS = ("Traceback", "File \"", "Exception", "psycopg", "sqlite3", "KeyError", "NoneType")


class Stack:
    def __init__(self, name: str, port: int) -> None:
        self.name, self.port = name, port
        self.base = f"http://localhost:{port}/api"
        self.env = {**os.environ, "RH_NAME": name, "RH_PORT": str(port)}
        jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # ── the shell side ──
    def sh(self, *args: str, extra_env: dict | None = None, check: bool = True) -> str:
        out = subprocess.run([str(ROOT / "scripts" / "rehearsal.sh"), *args], env={**self.env, **(extra_env or {})},
                             capture_output=True, text=True)
        if check and out.returncode != 0:
            raise RuntimeError(f"rehearsal.sh {' '.join(args)}: {out.stderr[-800:]}")
        return out.stdout.strip()

    def sql(self, q: str) -> str:
        return self.sh("sql", q)

    def dc(self, *args: str, check: bool = True) -> str:
        return self.sh("dc", *args, check=check)

    # ── the HTTP side ──
    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 120.0,
             files: tuple[str, bytes] | None = None) -> tuple[int, dict | str]:
        headers = {"X-Requested-With": "voltage"}
        data = None
        if files is not None:
            boundary = uuid.uuid4().hex
            name, blob = files
            parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"consent\"\r\n\r\ntrue\r\n".encode(),
                     f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                     f"Content-Type: video/mp4\r\n\r\n".encode() + blob + b"\r\n", f"--{boundary}--\r\n".encode()]
            data = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.http.open(req, timeout=timeout) as r:
                raw = r.read().decode() or "{}"
                return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            return 0, str(e)

    def ready(self, within: float = 180.0) -> float:
        start = time.time()
        while time.time() - start < within:
            code, _ = self.call("GET", "/ready", timeout=5)
            if code == 200:
                return time.time() - start
            time.sleep(2)
        raise RuntimeError(f"not ready after {within:.0f} s")

    def new_user(self) -> str:
        email = f"drill{int(time.time() * 1000)}@drill.test"
        self.call("POST", "/auth/signup", {"email": email, "password": "rehearsal-pass-1", "accept_terms": True})
        body = self.sql(f"select body from notify_outbox where to_addr='{email}' and kind='verify_email' order by id desc limit 1")
        token = body.split("verify?token=")[1].split()[0]
        self.call("GET", f"/auth/verify?token={token}")
        code, _ = self.call("POST", "/auth/password/login", {"email": email, "password": "rehearsal-pass-1"})
        assert code == 200, f"login {code}"
        return email

    def login(self, email: str) -> None:
        self.call("POST", "/auth/password/login", {"email": email, "password": "rehearsal-pass-1"})

    def upload(self) -> str:
        code, body = self.call("POST", "/videos", files=("sample-ad.mp4", CLIP.read_bytes()), timeout=180)
        assert code == 200, f"upload {code} {body}"
        return body["video_id"]

    def turn(self, video: str, text: str, approve: bool = False) -> tuple[int, dict | str]:
        return self.call("POST", f"/videos/{video}/turns", {"text": text, **({"approve": True} if approve else {})})

    def wait_job(self, job_id: str, within: float = 240.0) -> dict:
        start = time.time()
        last: dict = {}
        while time.time() - start < within:
            code, body = self.call("GET", f"/jobs/{job_id}", timeout=10)
            if code == 200 and isinstance(body, dict):
                last = body
                if body.get("status") in ("succeeded", "failed", "cancelled"):
                    return body
            time.sleep(2)
        return {**last, "status": last.get("status") or "unknown", "timed_out": True}

    def activity(self, video: str) -> list[dict]:
        code, body = self.call("GET", f"/videos/{video}/jobs", timeout=20)
        return body.get("jobs", []) if code == 200 and isinstance(body, dict) else []

    def chars_billed(self, video: str) -> int:
        out = self.sql(f"select coalesce(sum(units),0) from usage where project_id='{video}' and vendor='elevenlabs'")
        return int(float(out or 0))

    def takes(self, video: str) -> list[str]:
        out = self.sql(f"select body::json->'plan'->>'new_text' from candidates where project_id='{video}'")
        return [t for t in out.splitlines() if t]


# ── the four assertions ──

def no_job_stuck(s: Stack, video: str, settle: float = 60.0) -> tuple[bool, str]:
    start = time.time()
    while time.time() - start < settle:
        live = [j for j in s.activity(video) if j.get("status") in ("queued", "running")]
        if not live:
            return True, "nothing queued or running"
        time.sleep(3)
    return False, f"still live: {[(j.get('kind'), j.get('status')) for j in live]}"


def no_double_charge(s: Stack, video: str, takes_per_line: int = 3) -> tuple[bool, str]:
    billed = s.chars_billed(video)
    expected = sum(len(t) * takes_per_line for t in s.takes(video))
    return billed == expected, f"billed {billed} characters for takes worth {expected}"


def clear_status(s: Stack, video: str, extra: list[str] | None = None) -> tuple[bool, str]:
    failed = [j for j in s.activity(video) if j.get("status") in ("failed", "cancelled")]
    texts = [str(j.get("error_text") or "") for j in failed] + list(extra or [])
    bad = [t for t in texts if not t.strip() or any(w in t for w in TRACE_WORDS)]
    return (not bad), (f"failed jobs say: {texts[:4]}" if texts else "no failed job") + (f"; unclear: {bad}" if bad else "")


def recovers(s: Stack, video: str) -> tuple[bool, str]:
    code, job = s.turn(video, "Go ahead", approve=True)
    if code not in (200, 202):
        return False, f"go-ahead answered {code}: {job}"
    done = s.wait_job(job["job_id"])
    plan = (done.get("result") or {}).get("plan") or {}
    ready = [i for i in plan.get("items", []) if i.get("status") == "ready"]
    return done.get("status") == "succeeded" and bool(ready), f"go-ahead {done.get('status')}, {len(ready)} line(s) ready"


def asked(s: Stack, video: str) -> None:
    """A turn that ends with the paid question (the go-ahead comes later)."""
    code, job = s.turn(video, "Add a short line at the start")
    assert code in (200, 202), f"turn {code} {job}"
    s.wait_job(job["job_id"])


# ── the drills ──

def drill_kill_api(s: Stack) -> dict:
    s.sh("up", extra_env={"AVE_MOCK_SYNTH_SECONDS": "20"})
    s.ready()
    user = s.new_user()
    video = s.upload()
    asked(s, video)
    code, job = s.turn(video, "Go ahead", approve=True)
    deadline = time.time() + 90
    while time.time() < deadline and not any(j.get("kind") == "voice_line" and j.get("status") == "running" for j in s.activity(video)):
        time.sleep(1)
    was_voicing = any(j.get("kind") == "voice_line" and j.get("status") == "running" for j in s.activity(video))
    # A crash: SIGKILL to uvicorn's host process, as the kernel's OOM killer would send it. (Inside the
    # container PID 1 ignores its own namespace's SIGKILL, and `docker kill` counts as a manual stop,
    # which the restart policy does not undo.)
    pid = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", f"{s.name}-app-1"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["colima", "ssh", "--", "sudo", "kill", "-9", pid], capture_output=True, text=True)
    time.sleep(3)
    state = s.dc("ps", "-a", "--format", "{{.Service}} {{.State}} {{.Status}}", check=False)
    back = s.ready(240)
    s.login(user)
    steps = {"killed_while_voicing": was_voicing, "state_3s_after_kill": state, "back_after_s": round(back + 3, 1)}
    after_kill = s.wait_job(job["job_id"], within=30)
    steps["turn_after_kill"] = {k: after_kill.get(k) for k in ("status", "error")}
    s.sh("up")                                                          # the normal 2-6 s voice again
    s.ready()
    s.login(user)
    return run_asserts(s, video, steps, extra=[str(after_kill.get("error") or "")] if after_kill.get("status") == "failed" else None)


def drill_kill_worker(s: Stack) -> dict:
    s.sh("up")
    s.ready()
    user = s.new_user()
    video = s.upload()
    asked(s, video)
    s.dc("kill", "worker", check=False)
    time.sleep(5)
    state = s.dc("ps", "--format", "{{.Service}} {{.State}}", check=False)
    s.dc("up", "-d", "worker", check=False)
    s.login(user)
    return run_asserts(s, video, {"worker_after_kill": state})


def drill_restart_pg(s: Stack) -> dict:
    s.sh("up")
    s.ready()
    user = s.new_user()
    video = s.upload()
    asked(s, video)
    s.dc("restart", "postgres")
    first = [s.call("GET", "/videos", timeout=20)[0] for _ in range(3)]
    time.sleep(3)
    later = [s.call("GET", "/videos", timeout=20)[0] for _ in range(3)]
    code, _ = s.call("GET", "/ready", timeout=10)
    return run_asserts(s, video, {"first_answers": first, "answers_3s_later": later, "ready": code})


def drill_vendor(s: Stack, chaos: str, label: str) -> dict:
    s.sh("up", extra_env={"AVE_CHAOS": chaos, "AVE_CHAOS_FORCE": "1"})
    s.ready()
    user = s.new_user()
    video = s.upload()
    asked(s, video)
    code, job = s.turn(video, "Go ahead", approve=True)
    done = s.wait_job(job["job_id"], within=420) if code in (200, 202) else {"status": f"http {code}", "error": job}
    code_m, msgs = s.call("GET", f"/videos/{video}/messages?after=0")
    said = [m.get("text", "") for m in msgs if isinstance(m, dict) and m.get("role") == "assistant"][-2:] if code_m == 200 else []
    steps = {"chaos": chaos, "go_ahead": {k: done.get(k) for k in ("status", "error")}, "voltage_said": said}
    s.sh("up")                                                          # the fault clears
    s.ready()
    s.login(user)
    return run_asserts(s, video, steps, extra=said)


def drill_disk(s: Stack) -> dict:
    s.sh("up")
    s.ready()
    user = s.new_user()
    video = s.upload()
    asked(s, video)
    df = s.dc("exec", "-T", "app", "df", "-B1", "/data").splitlines()[-1].split()
    used, avail = int(df[2]), int(df[3])
    usable = used + avail                       # what df's Use% counts (the root-reserved 5% is not usable)
    fill = int(usable * 0.95) - used
    steps: dict = {"disk_bytes": usable, "used_before": round(used / usable, 3)}
    try:
        return _disk_full_steps(s, user, video, fill, steps)
    finally:
        s.dc("exec", "-T", "app", "rm", "-f", "/data/drill-fill", check=False)     # never leave the disk full


def _disk_full_steps(s: Stack, user: str, video: str, fill: int, steps: dict) -> dict:
    if fill > 0:
        s.dc("exec", "-T", "app", "fallocate", "-l", str(fill), "/data/drill-fill")
    df = s.dc("exec", "-T", "app", "df", "-B1", "/data").splitlines()[-1].split()
    steps["used_during"] = round(int(df[2]) / (int(df[2]) + int(df[3])), 3)
    code, body = s.call("POST", "/videos", files=("sample-ad.mp4", CLIP.read_bytes()), timeout=180)
    steps["upload_while_full"] = {"status": code, "said": body.get("detail") if isinstance(body, dict) else str(body)[:200]}
    code_r, _ = s.call("GET", "/ready", timeout=10)
    steps["ready_while_full"] = code_r
    code_t, job = s.turn(video, "Go ahead", approve=True)
    done = s.wait_job(job["job_id"]) if code_t in (200, 202) else {"status": f"http {code_t}", "error": job}
    steps["go_ahead_while_full"] = {k: done.get(k) for k in ("status", "error")}
    s.dc("exec", "-T", "app", "rm", "-f", "/data/drill-fill")
    steps["after_freeing"] = s.call("GET", "/ready", timeout=10)[0]
    extra = [steps["upload_while_full"]["said"] or ""] if code != 200 else []
    if done.get("status") == "failed":
        extra.append(str(done.get("error") or ""))
    return run_asserts(s, video, steps, extra=extra)


def run_asserts(s: Stack, video: str, steps: dict, extra: list[str] | None = None) -> dict:
    out = {"steps": steps, "video": video}
    for name, check in (("no_job_stuck", no_job_stuck), ("no_double_charge", no_double_charge)):
        ok, why = check(s, video)
        out[name] = {"ok": ok, "why": why}
    ok, why = clear_status(s, video, extra)
    out["clear_status"] = {"ok": ok, "why": why}
    ok, why = recovers(s, video)
    out["recovers"] = {"ok": ok, "why": why}
    ok, why = no_double_charge(s, video)                                # again, after the recovery's take
    out["no_double_charge_after_recovery"] = {"ok": ok, "why": why}
    out["passed"] = all(v["ok"] for k, v in out.items() if isinstance(v, dict) and "ok" in v)
    return out


DRILLS = {
    "kill-api": drill_kill_api,
    "kill-worker": drill_kill_worker,
    "restart-pg": drill_restart_pg,
    "vendor-500": lambda s: drill_vendor(s, "elevenlabs=status:500", "500"),
    "vendor-hang": lambda s: drill_vendor(s, "elevenlabs=hang:75;anthropic=hang:70@0.5", "hang"),
    "disk-95": drill_disk,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("drill", choices=[*DRILLS, "all"])
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--name", default="voltage-load")
    p.add_argument("--out", default="")
    a = p.parse_args(argv)
    names = list(DRILLS) if a.drill == "all" else [a.drill]
    results = {}
    for n in names:
        s = Stack(a.name, a.port)
        started = time.time()
        try:
            results[n] = DRILLS[n](s)
        except Exception as exc:  # noqa: BLE001 - a drill that cannot run is a result too
            results[n] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        results[n]["seconds"] = round(time.time() - started, 1)
        print(json.dumps({n: results[n]}, indent=2), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=2))
    return 0 if all(r.get("passed") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
