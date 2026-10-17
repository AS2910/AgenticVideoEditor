"""Put voices with an accent into the catalogue, from the ElevenLabs voice
library (15e).

    python -m app.tools.add_voices indian            # show what would be added
    python -m app.tools.add_voices indian --add      # add them to the account
    python -m app.tools.add_voices indian --add --max 6

The library is searched for English voices with that accent, most-used first;
the pick is balanced between women and men and skips voices already in the
account. Adding a voice takes one of the account's voice slots and bills no
characters; it can be removed in ElevenLabs → Voices. The key is never printed.
"""
from __future__ import annotations

import argparse
import sys

from app.adapters.elevenlabs import _add_from_library, _get_voices, _search_library
from app.config import load_settings


# Library descriptions that make a poor voice-over for most clips.
AVOID = ("dark", "suspens", "horror", "villain", "whisper", "asmr", "scary", "creepy", "intense")


def pick(candidates: list[dict], have: set[str], max_voices: int, names: list[str] = ()) -> list[dict]:
    """Up to `max_voices`: the ones named (by a word of their name), else
    alternating women and men by popularity, skipping the moody ones, none the
    account already has, none that need a paid plan the account lacks."""
    fresh = [c for c in candidates if c["voice_id"] not in have and c.get("free", True)]
    if names:
        wanted = [n.lower() for n in names]
        return [c for n in wanted for c in fresh if n in c["name"].lower()][:max_voices]
    fresh = [c for c in fresh if not any(w in (c["name"] + " " + c["description"]).lower() for w in AVOID)]
    women = [c for c in fresh if c.get("gender") == "female"]
    men = [c for c in fresh if c.get("gender") == "male"]
    out: list[dict] = []
    while len(out) < max_voices and (women or men):
        for pool in (women, men):
            if pool and len(out) < max_voices:
                out.append(pool.pop(0))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("accent", help='as the library labels it: "indian", "british", "australian", …')
    parser.add_argument("--add", action="store_true", help="add the picked voices to the account")
    parser.add_argument("--max", type=int, default=4, help="how many to add (default 4)")
    parser.add_argument("--language", default="en")
    parser.add_argument("--use-case", default="narrative_story",
                        help='the library\'s use case to search in (default narrative_story; "" for any)')
    parser.add_argument("--name", action="append", default=[],
                        help="pick a voice by a word of its library name (repeatable); overrides the balance")
    args = parser.parse_args(argv)

    settings = load_settings()
    key = settings.elevenlabs_api_key
    if not key:
        print("No ELEVENLABS_API_KEY in the environment or backend/.env.", file=sys.stderr)
        return 2
    have = {v["voice_id"] for v in _get_voices(key, 30.0)}
    found = _search_library(key, args.accent, 30.0, language=args.language, use_case=args.use_case or None)
    if not found:
        print(f"The library has no {args.language} voices labelled {args.accent!r}.")
        return 1
    chosen = pick(found, have, args.max, args.name)
    already = [v for v in found if v["voice_id"] in have]
    if already:
        print(f"Already in the account: {', '.join(v['name'] for v in already)}")
    if not chosen:
        print("Nothing new to add.")
        return 0
    print(f"{'Adding' if args.add else 'Would add'} {len(chosen)} {args.accent} {'voice' if len(chosen) == 1 else 'voices'}:")
    for v in chosen:
        who = ", ".join(str(x).replace("_", " ") for x in (v.get("gender"), v.get("age")) if x)
        print(f"  {v['name']}  ({who}; used by {v['uses']:,})")
        if args.add:
            status, voice_id, text = _add_from_library(key, v["public_owner_id"], v["voice_id"], v["name"], 30.0)
            print(f"    {'ok' if status == 200 else 'FAIL'} {voice_id or text[:120]}")
    if not args.add:
        print("Run again with --add to put them in the account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
