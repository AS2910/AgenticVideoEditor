"""LOAD.md's table from one k6 run: python3 tools/load/report.py <summary.json> <stats.csv>"""
import csv
import json
import sys

ORDER = ["POST /auth/password/login", "GET /auth/me", "GET /me/flags", "GET /videos", "GET /projects", "POST /videos (upload)",
         "GET /videos/{id}", "GET /videos/{id}/messages", "POST /videos/{id}/turns", "GET /jobs/{id}", "GET /videos/{id}/jobs",
         "POST /plans/{id}/approve (renders)", "POST /videos/{id}/export", "GET /billing"]


def s(ms):
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.0f} ms"


def main(summary, stats):
    m = json.load(open(summary))["metrics"]
    print("| Call | p50 | p95 | calls |\n|---|---|---|---|")
    for n in ORDER:
        v = m.get(f"http_req_duration{{name:{n}}}")
        if v:
            print(f"| `{n}` | {s(v['p(50)'])} | {s(v['p(95)'])} | {v['count']} |")
    for k, label in (("turn_queue_wait_ms", "Turn: queue wait (until running)"), ("turn_total_ms", "Turn: proposal ready"),
                     ("voice_turn_total_ms", "Go-ahead: line voiced and previewed")):
        v = m.get(k)
        if v:
            print(f"| {label} | {s(v['p(50)'])} | {s(v['p(95)'])} | {v['count']} |")
    print(f"\nSessions finished: {m['iterations']['count']}; failed requests: {m['http_req_failed']['passes']} of "
          f"{m['http_req_failed']['passes'] + m['http_req_failed']['fails']}; failed checks: {m['checks']['fails']}.")
    rows = list(csv.DictReader(open(stats)))
    for svc in ("app", "postgres", "web", "worker"):
        r = [x for x in rows if x["container"].endswith(f"-{svc}-1")]
        if r:
            cpu = [float(x["cpu_pct"]) for x in r]
            mem = [float(x["mem_mib"]) for x in r]
            print(f"- {svc}: CPU avg {sum(cpu) / len(cpu):.0f}%, max {max(cpu):.0f}% (of 400%); memory max {max(mem):.0f} MiB")


if __name__ == "__main__":
    main(*sys.argv[1:3])
