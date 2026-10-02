# Phase 8 — Free-form intent, and asking instead of refusing

**Date:** 2026-09-26 · **Roadmap:** Phase 8 (real intent parsing), pulled forward by first hands-on testing.

## Why now

The first real test (a portrait, speech-free clip) hit three walls:

1. Requests only worked in the `change "X" to "Y"` shape; "Add the line "Thirsty Thirsty"" and "make the background white" went through the same literal path.
2. A human can't drag a selection to the exact length of a line not yet spoken. When the line didn't fit, the edit was refused ("The new line is too short for the selection…") with no way forward.
3. On a clip with music and no speech, replacing the selection's audio wipes the music. There was no way to add a line *over* it, or *after* it.

## Decisions (from the user, 2026-09-26)

- **LLM:** Claude, `claude-opus-5`, effort `low` (a short parse; latency is user-facing). Key and workspace in `backend/.env` (`ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` — the key is not workspace-scoped, so every request carries `anthropic-workspace-id`).
- **When the line doesn't fit, ask** — offering only what applies:
  - shorter → *start at the selection's start* or *slow it to fill the selection*;
  - longer → *speed it up to fit* or *let it run past the selection* (when the video has room).
- **Stretch any amount, but warn** past the natural range (0.8×–1.25×).
- **How the line meets the original sound — ask when it applies:** *replace*, *layer on top*, or *concatenate*. Concatenate = the selection plays with its own sound, then the video holds the selection's last frame while the line plays; the video gets longer.

## Design

### Intent (`app/orchestrator/intent.py`, `app/adapters/claude_intent.py`)
`interpret(prompt, history, context) → Intent{action: speak|unsupported|clarify, new_text, mix|None, reply}`.
- `ClaudeInterpreter` — `messages.parse` with a Pydantic schema; told to leave `mix` null unless the request says it; told what the app can't do (visuals), so those get a plain reply.
- `RuleInterpreter` — the old regex, offline and free; used with no key or under `AVE_DRY_RUN`, and by the test suite.
- Chat history travels with each request (spec §5.8), so "now make it louder" has context.

### Placement (`EditPlan.fit`, `EditPlan.mix`)
- `fit`: `None` (auto, the old 0.8–1.25× rule) · `"start"` · `"stretch"`.
- `mix`: `"replace"` · `"layer"` · `"concatenate"`.
- Mix is asked *before* synthesis (free) when the selection holds no speech and the request didn't say. A selection with speech defaults to replace.
- Fit is asked *after* the first take, when auto-fit fails. That take is kept by the voice adapter and reused when the user answers — the question costs nothing extra.
- A take that doesn't fit is no longer silently regenerated: the user is asked.

### Render
- `layer`: the line is mixed over the original audio (fades on the line only).
- `concatenate`: an *insert* at the selection's end — the last frame held for the line's length (`tpad=stop_mode=clone`), video re-encoded.
- `start` with a longer line: the candidate's selection grows to the line's length, so the existing splice covers it.

### API
- `POST /edits/preview` gains `text`, `fit`, `mix`, `history`. Interpretation runs inside the job; the budget is checked there too.
- The job result is tagged: `type: "candidate" | "question" | "reply"`.

### Front end
- Chat shows both sides; questions render as option buttons (with the stretch warning); picking one re-submits with the choice.
- Export segments include inserts.

## Exit

- Backend + frontend suites green, lint/build clean.
- Live: the bird clip, "Add the line "Thirsty Thirsty"" → asked replace/layer/concatenate → asked start/stretch → candidate → export plays correctly; "make the background white" → a plain reply, no job failure.
