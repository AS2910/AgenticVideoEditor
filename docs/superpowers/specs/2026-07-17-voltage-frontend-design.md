# Voltage Front-End — Design

**Date:** 2026-07-17
**Status:** Approved for planning
**Scope:** The first web UI for the Agentic Video Editor v1 — a clickable "Voltage" editor wired to the existing mock backend. Real async job polling and backend-enforced consent are explicitly deferred and noted as future work.

Builds on: `docs/superpowers/specs/2026-07-14-agentic-video-editor-v1-design.md` (product v1 design) and the walking-skeleton backend now on `main`.

---

## 1. Goal

Build the full Voltage interaction model — play/pause → drag a timeline selection → prompt the agent → review a continuity-checked candidate → approve or iterate → export — as a **clickable UI shell** wired to the real mock backend endpoints, using a bundled sample video for the player.

This is not a throwaway prototype: the wiring, types, and components become the real UI once real generation vendors land. What's mocked is the *media and generation* (already mocked in the backend), not the interaction.

**Success criteria:** a user can, in the browser, complete the whole journey against the running backend — consent → load → select → prompt → preview a continuity scorecard → approve → export a segment manifest — and see the continuity failure path when it triggers.

---

## 2. Reality the design accounts for

The backend (four synchronous, deterministic endpoints) does **not** store or serve real video and does **not** generate real audio/frames:

- `POST /projects` takes `{filename, duration}` and returns a **canned** transcript ("Get 20% off today only", words 0.0–2.3s) plus a `project_id`.
- `POST /projects/{id}/edits/preview` returns a plan (new text + snapped selection), opaque refs (`audio://…`, `frames://…`), and a continuity report (four scores 0–1, `passed`, `warnings`).
- `POST /projects/{id}/edits` approves a candidate (or 422s if continuity failed).
- `POST /projects/{id}/export` returns a segment manifest (ordered `original`/`edited` spans).

Consequences the UI owns:

- **The player has no real footage** → we bundle a short sample video whose length is chosen to roughly match the ~2.3s transcript span, so the timeline and video don't look absurd together.
- **The transcript is canned** and won't truly correspond to the sample video's audio. Accepted for a shell — the timeline reflects the transcript the backend actually serves, so the *interaction* is real. This seam is documented, not hidden.
- **The candidate has no playable clip** → "review the candidate" is a **continuity scorecard**, not a video preview. This is also the exact shape a real preview card will take once media exists.
- **Consent is not a backend field yet** → the UI enforces the consent gate itself; backend enforcement is deferred.

---

## 3. Stack & repo shape

- **React + Vite + TypeScript.** Vite for fast dev/build; TypeScript for type-safe contracts against the FastAPI backend; plain CSS with CSS variables + CSS Modules for the custom Voltage theme (no UI kit — a component library would fight a bespoke dark theme). Vitest + React Testing Library for tests.
- New **`frontend/`** directory alongside `backend/`, making the repo a two-part monorepo.
- Vite dev server **proxies `/api/*`** to the FastAPI backend (default `http://127.0.0.1:8000`) so there are no CORS concerns and the client always calls same-origin `/api/...`.

---

## 4. Screen flow — three states, one page

A single-page app with a small top-level state machine in `App`: `consent → load → editor`.

### 4.1 Consent gate (spec-mandated, non-negotiable)
Before the editor is reachable, a modal presents: *"I confirm I have the right to edit and clone the speaker in this video."* A checkbox must be ticked to continue. Gates entry to the editor. Backend enforcement is future work; the UI owns the gate for now.

### 4.2 Load
A minimal start step: a **"Load sample ad"** button bundles a short sample video and calls `POST /projects` with its filename + duration. On success, stores `projectId` + `transcript` and transitions to the editor.

### 4.3 Editor (two-column Voltage layout)

```
┌─────────────────────────────────┬──────────────────────────┐
│  PLAYER (bundled sample video)  │   AGENT CHAT             │
│  ▶ play/pause, scrubber         │   ┌────────────────────┐ │
│                                 │   │ you: change "20%…" │ │
│  ─────────────────────────────  │   └────────────────────┘ │
│  TIMELINE                       │   ┌────────────────────┐ │
│  [Get][20%][off][today][only]   │   │ CANDIDATE CARD     │ │
│   ░░░▓▓▓▓▓▓▓▓░░░  ← glowing sel │   │ "30% off"          │ │
│      ▲ playhead                 │   │ ✓ Continuity 0.95… │ │
│                                 │   │ [Approve][Try again]│ │
│  [Export]                       │   └────────────────────┘ │
└─────────────────────────────────┴──────────────────────────┘
```

Left column = player + timeline + export. Right column = agent chat with the candidate card.

---

## 5. Components

Each has one clear job, a defined interface, and is testable in isolation.

- **`App`** — owns the `consent → load → editor` state machine and the shared editor state (`projectId`, `transcript`, current `selection`, `messages`, current `candidate`, `approvedEdits`, `exportManifest`).
- **`ConsentGate`** — the consent modal; calls back when confirmed.
- **`LoadScreen`** — the "Load sample ad" step; triggers project creation.
- **`Player`** — HTML5 `<video>` for the bundled sample, play/pause, scrubber; emits `currentTime`.
- **`Timeline`** — renders transcript words as blocks; drag to create/adjust a selection; renders the glowing selection region + playhead; visualizes boundary snapping (the selection reflects what the backend returns from preview). Emits `{start, end}`.
- **`ChatPanel`** — prompt input + message list; disables submit when prompt or selection is empty.
- **`CandidateCard`** — the continuity scorecard: new spoken text, "✓ Continuity checked" badge, four metric bars (voice_match, prosody, audio_integration, lip_sync) with scores, warnings, and Approve / Try-again buttons. On continuity fail, renders the "couldn't ship this" state instead.
- **`ExportBar`** — triggers export; renders the returned manifest as a horizontal strip of original/edited spans.
- **`api.ts`** — typed client wrapping the four endpoints.
- **`types.ts`** — shared TypeScript contracts mirroring the backend response shapes.

---

## 6. Data flow

Mirrors the four endpoints exactly:

1. **Load** → `POST /projects {filename, duration}` → store `project_id` + `transcript`.
2. **Select + prompt + Preview** → `POST /projects/{id}/edits/preview {prompt, start, end, voice_profile_id}` → render `CandidateCard`; update the timeline selection to the snapped range the backend returns.
3. **Approve** → `POST /projects/{id}/edits {…same payload}` → on 200, append to the in-panel edit list; on 422, flip the card to the continuity-failure state (never silently dropped).
4. **Export** → `POST /projects/{id}/export` → render the segment manifest strip.

**Synchronous with a simulated "generating" beat:** the backend responds instantly, but Preview shows a brief "Generating candidate…" state so the interaction reads like the real async job model the product spec envisions. The seam is in place for when jobs become truly async.

`voice_profile_id` defaults to `speaker-1` (the known-good profile); a hidden/dev affordance can send `unknown` to exercise the continuity-failure path.

---

## 7. Error handling

- **Network / unknown project** → inline error toast with a retry affordance.
- **Continuity fail (422 on approve)** → the candidate card surfaces the warnings and a "couldn't ship this" state; the edit is not appended. Honest, never silent.
- **Empty prompt or no selection** → Preview disabled with an inline hint.
- **Preview continuity below threshold** (200 but `passed: false`) → card renders with amber-glow bars and warnings; Approve is disabled so the user must iterate.

---

## 8. Visual system — "Voltage"

Palette (electric blue + cyan on near-black), as CSS variables:

| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#0A0E14` | near-black canvas |
| `--surface` | `#121721` | panels, cards |
| `--border` | `#1E2733` | dividers, card edges |
| `--electric` | `#2E6BFF` | primary action, playhead |
| `--cyan` | `#22D3EE` | selection glow, accents, ✓ |
| `--text` | `#E6EDF3` | body text |
| `--muted` | `#8B98A9` | secondary text |
| `--warn` | `#F5A524` | below-threshold warnings |
| `--pass` | `#22D3EE` | continuity pass |

Signature moments (what makes it read as "Voltage," not a generic dark theme):

- **Glowing selection region** on the timeline — cyan fill with an outer `box-shadow` bloom and bright drag-handles. The hero interaction.
- **Playhead** — a thin electric-blue line with a soft glow, tracking video time.
- **Continuity bars** — animate-fill on candidate arrival; ≥ threshold glow cyan, below-threshold glow amber; the "✓ Continuity checked" badge pulses subtly.
- **Approve button** — electric-blue with a hover glow; the primary visual weight in the panel.

Implementation: plain CSS transitions (no animation library). System font stack. The `frontend-design` skill is loaded at build time so components come out polished rather than boxy; the palette and signature moments above are the fixed brief.

---

## 9. Testing

Vitest + React Testing Library; no live backend in the suite (fetch is stubbed), matching the backend's TDD discipline.

- **`Timeline`** — drag produces the correct `{start, end}`; snapping visualization reflects the backend's returned selection.
- **`CandidateCard`** — renders the four scores and warnings; Approve/Try-again fire their callbacks; failure state renders on `passed: false`.
- **Integration** — a mocked-`api` test drives the full journey (load → preview → approve → export) and the 422 continuity-failure branch.

---

## 10. Deliberately deferred (not in this build)

- **Real async job polling** — jobs are synchronous now; a simulated "generating" beat stands in.
- **Backend-enforced consent** — the UI owns the gate; a backend consent field is future work.
- **Real video upload / storage / serving** and **real generation media** — bundled sample video + canned transcript stand in.
- **Multiple projects / project list / persistence** — single in-memory project per session, as the backend provides.
- **The `unknown`-voice failure trigger** is a dev affordance, not a user-facing feature.
