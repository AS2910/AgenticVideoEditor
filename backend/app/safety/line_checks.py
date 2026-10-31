"""Voice consent V1, step 4: the line checker behind `voice_guard.lines`.

    check(text, owner, video_id, voice_id) -> LineVerdict     one line, before it is voiced
    prepare(owner, video_id, texts)                           all of a video's lines in one model call

The rules run first (app.safety.line_rules, free, under 5 ms); a line they
block never reaches the model. Every other line goes to the check model
(app.adapters.claude_lines, Haiku 5.5) with the video's brief and its other
lines. The verdict: block when either says block; review when the rules hit a
claim, or the model says review or leaves the line out (unsure); else pass.

One call per video: `prepare` checks a batch's or a language version's lines
together, and a single `check` takes along every planned line of the video not
checked yet (`pending`), so the next lines are already answered. Answers are
kept an hour per video and text (`TTL_S`), in memory: a restart only costs a
call. A language version's translations of a master whose lines all passed
the model are checked by the rules only (`master_of`): Voltage wrote them from
lines already cleared (DECISIONS.md, step 4).

When the model call fails the verdict says so (`model_failed`) and the guard
picks the safe default (held for a cloned voice, a logged pass for any other).
With no model configured (no key, tests) the rules decide alone.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable

from app.safety import line_rules
from app.safety.voice_guard import LineVerdict

log = logging.getLogger("voltage.line_checks")

TTL_S = 3600.0
MAX_BATCH = 40
UNSURE = {"verdict": "review", "categories": ["unclear"], "reason": "The check model was not sure about this line."}


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


class LineChecks:
    def __init__(self, reader=None, *, context: Callable[[str], dict] = lambda video_id: {},
                 pending: Callable[[str], list[str]] = lambda video_id: [],
                 master_of: Callable[[str], str | None] = lambda video_id: None,
                 meter: Callable[[str], object] = lambda video_id: None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.reader = reader
        self.context, self.pending, self.master_of, self.meter, self.clock = context, pending, master_of, meter, clock
        self._kept: dict[tuple[str, str], tuple[float, dict]] = {}
        self._clear: dict[str, tuple[float, int]] = {}         # master video -> (when, translations it may still clear)
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return line_rules.VERSION + (f" + {self.reader.model}" if self.reader is not None else "")

    # ── the cache ──

    def _get(self, video_id: str, h: str) -> dict | None:
        with self._lock:
            found = self._kept.get((video_id, h))
            if found is None or self.clock() - found[0] > TTL_S:
                return None
            return found[1]

    def _put(self, video_id: str, h: str, answer: dict) -> None:
        with self._lock:
            now = self.clock()
            if len(self._kept) > 5000:
                self._kept = {k: v for k, v in self._kept.items() if now - v[0] <= TTL_S}
            self._kept[(video_id, h)] = (now, answer)

    def _master_clear(self, video_id: str) -> bool:
        """A language version whose master's lines all passed the model: take one of its translations on the rules."""
        master = self.master_of(video_id) if video_id else None
        if not master:
            return False
        with self._lock:
            found = self._clear.get(master)
            if found is None or self.clock() - found[0] > TTL_S or found[1] <= 0:
                return False
            self._clear[master] = (found[0], found[1] - 1)
            return True

    # ── the model ──

    def _ask(self, video_id: str, texts: list[str]) -> tuple[dict[str, dict], int]:
        """One model call over these texts (by hash). Raises when the call fails."""
        lines = [{"id": str(n), "text": t} for n, t in enumerate(texts, 1)]
        started = time.perf_counter()
        context = {}
        try:
            context = self.context(video_id) if video_id else {}
        except Exception:  # noqa: BLE001 - context is a help, never a reason to fail the check
            log.warning("line check: no context for %s", video_id, exc_info=True)
        answers = self.reader.read(lines, context, meter=self.meter(video_id) if video_id else None)
        took = int((time.perf_counter() - started) * 1000)
        out = {}
        for ln in lines:
            answer = answers.get(ln["id"]) or UNSURE
            out[_hash(ln["text"])] = answer
            self._put(video_id or "", _hash(ln["text"]), answer)
        return out, took

    def _batch(self, video_id: str | None, first: list[str]) -> list[str]:
        """These lines, then the video's other planned lines the rules pass and no answer covers yet."""
        seen, out = set(), []
        try:
            more = self.pending(video_id) if video_id else []
        except Exception:  # noqa: BLE001 - only an optimisation
            more = []
        for t in list(first) + list(more or []):
            h = _hash(t)
            if not (t or "").strip() or h in seen or len(out) >= MAX_BATCH:
                continue
            seen.add(h)
            if t not in first and (self._get(video_id or "", h) is not None or line_rules.check(t).verdict == "block"):
                continue
            out.append(t)
        return out

    # ── the verdict ──

    @staticmethod
    def combine(rules: line_rules.RuleResult, answer: dict | None, model: str, took: int | None = None) -> LineVerdict:
        hits = rules.hits
        if rules.verdict == "block":
            return LineVerdict("block", rules.categories, line_rules.VERSION, hits, "The line matched the rules.")
        if answer is None:                                   # rules only
            return LineVerdict(rules.verdict, rules.categories, model, hits,
                               "The line matched the rules for claims." if rules.verdict == "review" else "", model_ms=took)
        cats = tuple(dict.fromkeys(list(answer.get("categories") or [])))
        if answer["verdict"] == "block":
            return LineVerdict("block", cats or ("unclear",), model, hits, answer.get("reason") or "", model_ms=took)
        if answer["verdict"] == "review" or rules.verdict == "review":
            both = tuple(dict.fromkeys(list(rules.categories) + list(cats))) or ("unclear",)
            return LineVerdict("review", both, model, hits, answer.get("reason") or "The line matched the rules for claims.",
                               model_ms=took)
        return LineVerdict("pass", (), model, hits, "", model_ms=took)

    def check(self, text: str, *, owner: str, video_id: str | None, voice_id: str | None) -> LineVerdict:
        rules = line_rules.check(text)
        if rules.verdict == "block" or self.reader is None:
            return self.combine(rules, None, self.name)
        h = _hash(text)
        answer = self._get(video_id or "", h)
        if answer is not None:
            return self.combine(rules, answer, self.name)
        if self._master_clear(video_id or ""):
            return self.combine(rules, None, f"{self.name} (the master's lines)")
        try:
            answers, took = self._ask(video_id or "", self._batch(video_id, [text]))
        except Exception as exc:  # noqa: BLE001 - the guard picks the safe default
            log.warning("line check model failed for %s: %s", video_id, exc)
            verdict = self.combine(rules, None, self.name)
            return LineVerdict(verdict.verdict, verdict.categories, verdict.model, verdict.rule_hits,
                               f"The check model did not answer ({type(exc).__name__}).", model_failed=True)
        return self.combine(rules, answers.get(h) or UNSURE, self.name, took)

    def prepare(self, owner: str, video_id: str, texts: list[str]) -> int:
        """Check all these lines of one video in one model call, ahead of voicing them.
        Returns how many went to the model. When every one passed, the video's
        language versions may take their translations on the rules (`master_of`)."""
        if self.reader is None:
            return 0
        todo = self._batch(video_id, [t for t in texts if line_rules.check(t).verdict != "block"
                                      and self._get(video_id, _hash(t)) is None])
        answers: dict[str, dict] = {}
        if todo:
            answers, _ = self._ask(video_id, todo)
        every = [self._get(video_id, _hash(t)) for t in texts if (t or "").strip()]
        if every and all(a is not None and a["verdict"] == "pass" for a in every) \
                and all(line_rules.check(t).verdict == "pass" for t in texts):
            with self._lock:
                self._clear[video_id] = (self.clock(), 2 * len(every) * 4)   # a few languages, a retry each
        return len(answers)
