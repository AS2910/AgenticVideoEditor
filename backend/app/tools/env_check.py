"""Launch item 11: is every variable production needs set?

    python -m app.tools.env_check [--env-file .env.production]

Reads the env file (KEY=VALUE lines; the real environment wins) and prints
what production would refuse to start without (app/config.py
`production_problems`). Exits 1 when anything is missing.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.config import REQUIRED_IN_PRODUCTION, production_problems


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.env_check")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    env = read_env_file(Path(args.env_file)) if args.env_file and Path(args.env_file).is_file() else {}
    env.update({k: v for k, v in os.environ.items() if v})
    problems = production_problems(env)
    print(f"required in production: {', '.join(name for name, _ in REQUIRED_IN_PRODUCTION)}")
    for p in problems:
        print(f"MISSING {p}")
    print("env: ok" if not problems else f"env: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
