# Voltage Front-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the clickable "Voltage" editor UI — consent gate → load → timeline selection → agent prompt → continuity-scorecard candidate → approve/iterate → export — as a React app wired to the existing mock backend.

**Architecture:** A single-page React app in a new `frontend/` directory beside `backend/`. A top-level state machine (`consent → load → editor`) in `App` owns shared state; focused components each do one job and talk to the backend through one typed API client. The Vite dev server proxies `/api/*` to FastAPI (:8000) so the client always calls same-origin. Media and generation are mocked (bundled sample video + the backend's canned transcript + continuity scorecard instead of a real clip).

**Tech Stack:** React 18, Vite, TypeScript, plain CSS + CSS Modules (Voltage theme via CSS variables), Vitest + React Testing Library + jsdom. No UI kit, no animation library.

## Global Constraints

- **Stack:** React + Vite + TypeScript only. No component library (Material/Chakra/etc.). No animation library — plain CSS transitions.
- **Location:** all front-end code under `frontend/`. Backend is untouched by this plan.
- **API base:** the client calls `/api/...`; Vite proxies `/api` → `http://127.0.0.1:8000` with the `/api` prefix stripped. Backend routes are `/projects`, `/projects/{id}/edits/preview`, `/projects/{id}/edits`, `/projects/{id}/export` — all `POST`.
- **Palette (CSS variables, exact values):** `--bg: #0A0E14`, `--surface: #121721`, `--border: #1E2733`, `--electric: #2E6BFF`, `--cyan: #22D3EE`, `--text: #E6EDF3`, `--muted: #8B98A9`, `--warn: #F5A524`, `--pass: #22D3EE`.
- **Continuity metrics, in fixed order:** `voice_match`, `prosody`, `audio_integration`, `lip_sync`. Threshold for "pass"/glow is `>= 0.8`.
- **Default voice profile:** `speaker-1` (known-good). `unknown` is a dev-only affordance that forces the continuity-failure path.
- **Tests:** no live backend — `fetch` is stubbed in every test. Match the backend's TDD discipline: test fails first, then implement.
- **Consent copy (verbatim):** "I confirm I have the right to edit and clone the speaker in this video."

---

## File Structure

- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`, `frontend/index.html` — scaffold + proxy + Vitest config
- `frontend/vitest.setup.ts` — jest-dom matchers
- `frontend/src/main.tsx` — React entry
- `frontend/src/styles/theme.css` — Voltage CSS variables + base styles
- `frontend/src/types.ts` — API contracts mirroring the backend
- `frontend/src/api.ts` — typed client + `ApiError`
- `frontend/src/timeline/selection.ts` — pure helper `timeFromX()` (drag math)
- `frontend/src/components/ConsentGate.tsx` + `.module.css`
- `frontend/src/components/LoadScreen.tsx` + `.module.css`
- `frontend/src/components/Player.tsx` + `.module.css`
- `frontend/src/components/Timeline.tsx` + `.module.css`
- `frontend/src/components/ChatPanel.tsx` + `.module.css`
- `frontend/src/components/CandidateCard.tsx` + `.module.css`
- `frontend/src/components/ExportBar.tsx` + `.module.css`
- `frontend/src/App.tsx` + `.module.css` — state machine + wiring
- `frontend/public/sample-ad.mp4` — bundled sample video (or generated placeholder)
- `frontend/src/**/*.test.tsx` — one test module per unit

---

### Task 0: Scaffold Vite + React + TS with proxy, Vitest, and theme

**Files:**
- Create: `frontend/` via Vite template, then add `frontend/vite.config.ts`, `frontend/vitest.setup.ts`, `frontend/src/styles/theme.css`
- Test: `frontend/src/smoke.test.ts`

**Interfaces:**
- Produces: a runnable dev server (`npm run dev`) proxying `/api`, and a passing Vitest run (`npm test`).

- [ ] **Step 1: Scaffold the project**

Run from repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

- [ ] **Step 2: Write `frontend/vite.config.ts`** (proxy + Vitest config)

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './vitest.setup.ts',
    css: true,
  },
})
```

- [ ] **Step 3: Write `frontend/vitest.setup.ts`**

```ts
import '@testing-library/jest-dom'
```

- [ ] **Step 4: Add the `test` script to `frontend/package.json`**

In the `"scripts"` block add:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 5: Write `frontend/src/styles/theme.css`**

```css
:root {
  --bg: #0A0E14;
  --surface: #121721;
  --border: #1E2733;
  --electric: #2E6BFF;
  --cyan: #22D3EE;
  --text: #E6EDF3;
  --muted: #8B98A9;
  --warn: #F5A524;
  --pass: #22D3EE;
  --radius: 10px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
button { font: inherit; cursor: pointer; }
```

Import it once in `frontend/src/main.tsx` (add `import './styles/theme.css'` at the top; remove the template's `import './index.css'` if present).

- [ ] **Step 6: Write the smoke test `frontend/src/smoke.test.ts`**

```ts
import { describe, it, expect } from 'vitest'

describe('toolchain', () => {
  it('runs vitest', () => {
    expect(1 + 1).toBe(2)
  })
})
```

- [ ] **Step 7: Run the test**

Run: `cd frontend && npm test`
Expected: PASS (1 test). If the template shipped `App.test` variants that fail, delete the template's default `src/App.css`/demo test noise is fine to keep; only ensure the suite is green.

- [ ] **Step 8: Add `.gitignore` and commit**

Ensure `frontend/.gitignore` (from the template) contains `node_modules` and `dist`. Then:
```bash
git add frontend
git commit -m "chore: scaffold Vite React TS frontend with proxy and vitest"
```

---

### Task 1: API types and typed client

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Produces:
  - Types: `Word{text:string,start:number,end:number}`, `Selection{start:number,end:number}`, `ContinuityReport{voice_match:number,prosody:number,audio_integration:number,lip_sync:number,passed:boolean,warnings:string[]}`, `EditPlan{selection:Selection,new_text:string,voice_profile_id:string}`, `Candidate{plan:EditPlan,audio_ref:string,frames_ref:string,continuity:ContinuityReport}`, `Project{project_id:string,transcript:Word[]}`, `ApprovedResult{edit_id:string,continuity:ContinuityReport}`, `Segment{start:number,end:number,kind:'original'|'edited',ref:string}`, `ExportManifest{segments:Segment[]}`, `EditRequest{prompt:string,start:number,end:number,voice_profile_id:string}`
  - `class ApiError extends Error { status: number }`
  - `createProject(filename:string,duration:number):Promise<Project>`
  - `previewEdit(id:string,req:EditRequest):Promise<Candidate>`
  - `approveEdit(id:string,req:EditRequest):Promise<ApprovedResult>`
  - `exportProject(id:string):Promise<ExportManifest>`

- [ ] **Step 1: Write `frontend/src/types.ts`**

```ts
export interface Word { text: string; start: number; end: number }
export interface Selection { start: number; end: number }

export interface ContinuityReport {
  voice_match: number
  prosody: number
  audio_integration: number
  lip_sync: number
  passed: boolean
  warnings: string[]
}

export interface EditPlan {
  selection: Selection
  new_text: string
  voice_profile_id: string
}

export interface Candidate {
  plan: EditPlan
  audio_ref: string
  frames_ref: string
  continuity: ContinuityReport
}

export interface Project { project_id: string; transcript: Word[] }
export interface ApprovedResult { edit_id: string; continuity: ContinuityReport }
export interface Segment { start: number; end: number; kind: 'original' | 'edited'; ref: string }
export interface ExportManifest { segments: Segment[] }

export interface EditRequest {
  prompt: string
  start: number
  end: number
  voice_profile_id: string
}
```

- [ ] **Step 2: Write the failing test `frontend/src/api.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createProject, previewEdit, approveEdit, exportProject, ApiError } from './api'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response)
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

describe('api client', () => {
  it('createProject posts filename+duration to /api/projects', async () => {
    const f = mockFetch(200, { project_id: 'p1', transcript: [] })
    vi.stubGlobal('fetch', f)
    const project = await createProject('ad.mp4', 30)
    expect(project.project_id).toBe('p1')
    const [url, opts] = f.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ filename: 'ad.mp4', duration: 30 })
  })

  it('previewEdit posts the edit request to the preview route', async () => {
    const f = mockFetch(200, { plan: {}, audio_ref: 'a', frames_ref: 'f', continuity: {} })
    vi.stubGlobal('fetch', f)
    await previewEdit('p1', { prompt: 'x', start: 0.5, end: 1, voice_profile_id: 'speaker-1' })
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits/preview')
  })

  it('approveEdit hits the edits route', async () => {
    const f = mockFetch(200, { edit_id: 'e1', continuity: {} })
    vi.stubGlobal('fetch', f)
    const res = await approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'speaker-1' })
    expect(res.edit_id).toBe('e1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits')
  })

  it('exportProject posts to the export route', async () => {
    const f = mockFetch(200, { segments: [] })
    vi.stubGlobal('fetch', f)
    await exportProject('p1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/export')
  })

  it('throws ApiError with status on non-2xx', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { detail: 'continuity check failed' }))
    await expect(
      approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'unknown' }),
    ).rejects.toMatchObject({ status: 422 })
    expect(
      approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'unknown' }),
    ).rejects.toBeInstanceOf(ApiError)
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: FAIL — `Cannot find module './api'`.

- [ ] **Step 4: Write `frontend/src/api.ts`**

```ts
import type {
  Project, Candidate, ApprovedResult, ExportManifest, EditRequest,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    throw new ApiError(res.status, await res.text())
  }
  return (await res.json()) as T
}

export const createProject = (filename: string, duration: number) =>
  post<Project>('/projects', { filename, duration })

export const previewEdit = (id: string, req: EditRequest) =>
  post<Candidate>(`/projects/${id}/edits/preview`, req)

export const approveEdit = (id: string, req: EditRequest) =>
  post<ApprovedResult>(`/projects/${id}/edits`, req)

export const exportProject = (id: string) =>
  post<ExportManifest>(`/projects/${id}/export`)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat: add typed API client for the edit lifecycle"
```

---

### Task 2: ConsentGate

**Files:**
- Create: `frontend/src/components/ConsentGate.tsx`, `frontend/src/components/ConsentGate.module.css`
- Test: `frontend/src/components/ConsentGate.test.tsx`

**Interfaces:**
- Produces: `ConsentGate({ onConfirm }: { onConfirm: () => void })`. Renders the consent copy + a checkbox + a "Continue" button. Continue is disabled until the checkbox is checked; clicking it calls `onConfirm`.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentGate } from './ConsentGate'

describe('ConsentGate', () => {
  it('shows the consent copy and gates Continue on the checkbox', async () => {
    const onConfirm = vi.fn()
    render(<ConsentGate onConfirm={onConfirm} />)
    expect(
      screen.getByText(/right to edit and clone the speaker/i),
    ).toBeInTheDocument()

    const button = screen.getByRole('button', { name: /continue/i })
    expect(button).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox'))
    expect(button).toBeEnabled()

    await userEvent.click(button)
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/ConsentGate.test.tsx`
Expected: FAIL — cannot find module `./ConsentGate`.

- [ ] **Step 3: Write `ConsentGate.tsx`**

```tsx
import { useState } from 'react'
import styles from './ConsentGate.module.css'

export function ConsentGate({ onConfirm }: { onConfirm: () => void }) {
  const [checked, setChecked] = useState(false)
  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <h1 className={styles.title}>Before you edit</h1>
        <label className={styles.consent}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
          />
          <span>I confirm I have the right to edit and clone the speaker in this video.</span>
        </label>
        <button className={styles.continue} disabled={!checked} onClick={onConfirm}>
          Continue
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `ConsentGate.module.css`**

```css
.overlay {
  position: fixed; inset: 0;
  display: grid; place-items: center;
  background: rgba(5, 8, 12, 0.9);
}
.modal {
  width: min(480px, 90vw);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px;
}
.title { margin: 0 0 20px; font-size: 20px; }
.consent { display: flex; gap: 12px; align-items: flex-start; color: var(--text); margin-bottom: 24px; }
.continue {
  width: 100%; padding: 12px;
  background: var(--electric); color: white; border: none; border-radius: 8px;
  box-shadow: 0 0 20px rgba(46, 107, 255, 0.4);
}
.continue:disabled { background: var(--border); color: var(--muted); box-shadow: none; cursor: not-allowed; }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/ConsentGate.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConsentGate.*
git commit -m "feat: add consent gate"
```

---

### Task 3: LoadScreen

**Files:**
- Create: `frontend/src/components/LoadScreen.tsx`, `frontend/src/components/LoadScreen.module.css`
- Test: `frontend/src/components/LoadScreen.test.tsx`

**Interfaces:**
- Produces: `LoadScreen({ onLoad, loading }: { onLoad: () => void; loading: boolean })`. Renders a "Load sample ad" button that calls `onLoad`; when `loading` is true the button shows "Loading…" and is disabled.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoadScreen } from './LoadScreen'

describe('LoadScreen', () => {
  it('calls onLoad when the button is clicked', async () => {
    const onLoad = vi.fn()
    render(<LoadScreen onLoad={onLoad} loading={false} />)
    await userEvent.click(screen.getByRole('button', { name: /load sample ad/i }))
    expect(onLoad).toHaveBeenCalledOnce()
  })

  it('disables and relabels the button while loading', () => {
    render(<LoadScreen onLoad={() => {}} loading={true} />)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent(/loading/i)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/LoadScreen.test.tsx`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `LoadScreen.tsx`**

```tsx
import styles from './LoadScreen.module.css'

export function LoadScreen({ onLoad, loading }: { onLoad: () => void; loading: boolean }) {
  return (
    <div className={styles.screen}>
      <div className={styles.brand}>Voltage</div>
      <p className={styles.tagline}>Edit what was already shot — seamlessly.</p>
      <button className={styles.load} onClick={onLoad} disabled={loading}>
        {loading ? 'Loading…' : 'Load sample ad'}
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Write `LoadScreen.module.css`**

```css
.screen { min-height: 100vh; display: grid; place-content: center; justify-items: center; gap: 16px; }
.brand { font-size: 40px; font-weight: 700; color: var(--cyan); text-shadow: 0 0 24px rgba(34, 211, 238, 0.5); }
.tagline { color: var(--muted); margin: 0; }
.load {
  margin-top: 8px; padding: 12px 28px;
  background: var(--electric); color: white; border: none; border-radius: 8px;
  box-shadow: 0 0 20px rgba(46, 107, 255, 0.4);
}
.load:disabled { background: var(--border); color: var(--muted); box-shadow: none; }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/LoadScreen.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/LoadScreen.*
git commit -m "feat: add load screen"
```

---

### Task 4: Player

**Files:**
- Create: `frontend/src/components/Player.tsx`, `frontend/src/components/Player.module.css`
- Test: `frontend/src/components/Player.test.tsx`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `Player({ src, duration, currentTime, onSeek }: { src: string; duration: number; currentTime: number; onSeek: (t: number) => void })`. Renders a `<video>` (with the src) and a range scrubber (min 0, max `duration`, value `currentTime`); dragging the scrubber calls `onSeek`. A play/pause button toggles the video and its own label. Falls back to a gradient placeholder panel if the video can't load, but the scrubber still works.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { Player } from './Player'

describe('Player', () => {
  it('renders a scrubber bound to duration and reports seeks', () => {
    const onSeek = vi.fn()
    render(<Player src="/sample-ad.mp4" duration={2.3} currentTime={0} onSeek={onSeek} />)
    const scrubber = screen.getByRole('slider')
    expect(scrubber).toHaveAttribute('max', '2.3')
    fireEvent.change(scrubber, { target: { value: '1.1' } })
    expect(onSeek).toHaveBeenCalledWith(1.1)
  })

  it('has a play/pause control', () => {
    render(<Player src="/sample-ad.mp4" duration={2.3} currentTime={0} onSeek={() => {}} />)
    expect(screen.getByRole('button', { name: /play|pause/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/Player.test.tsx`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `Player.tsx`**

```tsx
import { useRef, useState } from 'react'
import styles from './Player.module.css'

interface PlayerProps {
  src: string
  duration: number
  currentTime: number
  onSeek: (t: number) => void
}

export function Player({ src, duration, currentTime, onSeek }: PlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)

  const toggle = () => {
    const video = videoRef.current
    if (video) {
      if (playing) video.pause()
      else void video.play().catch(() => {})
    }
    setPlaying((p) => !p)
  }

  return (
    <div className={styles.player}>
      <div className={styles.stage}>
        <video ref={videoRef} className={styles.video} src={src} muted playsInline />
      </div>
      <div className={styles.controls}>
        <button className={styles.play} onClick={toggle}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <input
          className={styles.scrubber}
          type="range"
          min={0}
          max={duration}
          step={0.01}
          value={currentTime}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Seek"
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `Player.module.css`**

```css
.player { display: flex; flex-direction: column; gap: 12px; }
.stage {
  aspect-ratio: 16 / 9; border-radius: var(--radius); overflow: hidden;
  background: linear-gradient(135deg, #0d1a2b, #0a0e14);
  border: 1px solid var(--border);
  display: grid; place-items: center;
}
.video { width: 100%; height: 100%; object-fit: cover; }
.controls { display: flex; gap: 12px; align-items: center; }
.play {
  padding: 8px 18px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text);
}
.scrubber { flex: 1; accent-color: var(--electric); }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/Player.test.tsx`
Expected: PASS (2 tests). (jsdom does not implement `HTMLMediaElement.play`; the test only exercises the scrubber and the button's presence, not real playback.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Player.*
git commit -m "feat: add video player with scrubber"
```

---

### Task 5: Timeline (selection math + component)

**Files:**
- Create: `frontend/src/timeline/selection.ts`, `frontend/src/components/Timeline.tsx`, `frontend/src/components/Timeline.module.css`
- Test: `frontend/src/timeline/selection.test.ts`, `frontend/src/components/Timeline.test.tsx`

**Interfaces:**
- Consumes: `Word`, `Selection` from `types.ts`.
- Produces:
  - `timeFromX(clientX:number, rectLeft:number, rectWidth:number, duration:number):number` — pure helper mapping a pixel x within the track to a clamped time in `[0, duration]`.
  - `Timeline({ words, duration, selection, currentTime, onSelect }: { words: Word[]; duration: number; selection: Selection | null; currentTime: number; onSelect: (s: Selection) => void })`. Renders each word as a block positioned by time; clicking a word selects that word's `{start, end}`; renders the glowing selection region (positioned by `selection`) and the playhead (positioned by `currentTime`).

- [ ] **Step 1: Write the failing helper test `selection.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { timeFromX } from './selection'

describe('timeFromX', () => {
  it('maps the track midpoint to half the duration', () => {
    // track from x=100 to x=300 (width 200), duration 2.3
    expect(timeFromX(200, 100, 200, 2.3)).toBeCloseTo(1.15)
  })
  it('clamps below the track to 0', () => {
    expect(timeFromX(50, 100, 200, 2.3)).toBe(0)
  })
  it('clamps past the track to the duration', () => {
    expect(timeFromX(500, 100, 200, 2.3)).toBe(2.3)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/timeline/selection.test.ts`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `selection.ts`**

```ts
export function timeFromX(
  clientX: number,
  rectLeft: number,
  rectWidth: number,
  duration: number,
): number {
  if (rectWidth <= 0) return 0
  const ratio = (clientX - rectLeft) / rectWidth
  const clamped = Math.min(1, Math.max(0, ratio))
  return clamped * duration
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/timeline/selection.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the failing component test `Timeline.test.tsx`**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Timeline } from './Timeline'
import type { Word } from '../types'

const WORDS: Word[] = [
  { text: 'Get', start: 0.0, end: 0.4 },
  { text: '20%', start: 0.4, end: 0.9 },
  { text: 'off', start: 0.9, end: 1.3 },
]

describe('Timeline', () => {
  it('selects a word span when a word is clicked', async () => {
    const onSelect = vi.fn()
    render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={onSelect} />,
    )
    await userEvent.click(screen.getByText('20%'))
    expect(onSelect).toHaveBeenCalledWith({ start: 0.4, end: 0.9 })
  })

  it('renders a selection region when a selection is present', () => {
    render(
      <Timeline
        words={WORDS}
        duration={2.3}
        selection={{ start: 0.4, end: 1.3 }}
        currentTime={0}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByTestId('selection-region')).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/Timeline.test.tsx`
Expected: FAIL — cannot find module `./Timeline`.

- [ ] **Step 7: Write `Timeline.tsx`**

```tsx
import type { Word, Selection } from '../types'
import styles from './Timeline.module.css'

interface TimelineProps {
  words: Word[]
  duration: number
  selection: Selection | null
  currentTime: number
  onSelect: (s: Selection) => void
}

const pct = (t: number, duration: number) => `${(t / duration) * 100}%`

export function Timeline({ words, duration, selection, currentTime, onSelect }: TimelineProps) {
  return (
    <div className={styles.timeline}>
      <div className={styles.track}>
        {words.map((w) => (
          <button
            key={`${w.text}-${w.start}`}
            className={styles.word}
            style={{ left: pct(w.start, duration), width: pct(w.end - w.start, duration) }}
            onClick={() => onSelect({ start: w.start, end: w.end })}
          >
            {w.text}
          </button>
        ))}

        {selection && (
          <div
            data-testid="selection-region"
            className={styles.selection}
            style={{
              left: pct(selection.start, duration),
              width: pct(selection.end - selection.start, duration),
            }}
          />
        )}

        <div className={styles.playhead} style={{ left: pct(currentTime, duration) }} />
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Write `Timeline.module.css`**

```css
.timeline { padding: 8px 0; }
.track {
  position: relative; height: 56px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
.word {
  position: absolute; top: 8px; height: 40px;
  background: transparent; color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  font-size: 12px; white-space: nowrap; overflow: hidden;
}
.selection {
  position: absolute; top: 0; height: 100%;
  background: rgba(34, 211, 238, 0.18);
  border: 1px solid var(--cyan);
  box-shadow: 0 0 18px rgba(34, 211, 238, 0.5);
  pointer-events: none; border-radius: 6px;
}
.playhead {
  position: absolute; top: -4px; height: calc(100% + 8px); width: 2px;
  background: var(--electric); box-shadow: 0 0 10px var(--electric);
  pointer-events: none;
}
```

- [ ] **Step 9: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/Timeline.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/timeline frontend/src/components/Timeline.*
git commit -m "feat: add timeline with word selection and glowing region"
```

---

### Task 6: ChatPanel

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`, `frontend/src/components/ChatPanel.module.css`
- Test: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Produces: `ChatPanel({ messages, canSubmit, onSubmit, children }: { messages: string[]; canSubmit: boolean; onSubmit: (prompt: string) => void; children?: React.ReactNode })`. Renders the message list, an optional `children` slot (used by `App` to mount the candidate card), and a prompt input + Preview button. The button is disabled when `canSubmit` is false or the input is empty; submitting calls `onSubmit(prompt)` and clears the input.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatPanel } from './ChatPanel'

describe('ChatPanel', () => {
  it('disables Preview when canSubmit is false', () => {
    render(<ChatPanel messages={[]} canSubmit={false} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /preview/i })).toBeDisabled()
  })

  it('submits the typed prompt and clears the input', async () => {
    const onSubmit = vi.fn()
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={onSubmit} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'change "20% off" to "30% off"')
    await userEvent.click(screen.getByRole('button', { name: /preview/i }))
    expect(onSubmit).toHaveBeenCalledWith('change "20% off" to "30% off"')
    expect(input).toHaveValue('')
  })

  it('renders prior messages', () => {
    render(<ChatPanel messages={['hello there']} canSubmit={true} onSubmit={() => {}} />)
    expect(screen.getByText('hello there')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `ChatPanel.tsx`**

```tsx
import { useState } from 'react'
import styles from './ChatPanel.module.css'

interface ChatPanelProps {
  messages: string[]
  canSubmit: boolean
  onSubmit: (prompt: string) => void
  children?: React.ReactNode
}

export function ChatPanel({ messages, canSubmit, onSubmit, children }: ChatPanelProps) {
  const [prompt, setPrompt] = useState('')
  const disabled = !canSubmit || prompt.trim() === ''

  const submit = () => {
    if (disabled) return
    onSubmit(prompt.trim())
    setPrompt('')
  }

  return (
    <div className={styles.panel}>
      <div className={styles.messages}>
        {messages.map((m, i) => (
          <div key={i} className={styles.message}>{m}</div>
        ))}
        {children}
      </div>
      <div className={styles.composer}>
        <input
          className={styles.input}
          type="text"
          placeholder='e.g. change "20% off" to "30% off"'
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
        />
        <button className={styles.preview} onClick={submit} disabled={disabled}>
          Preview
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `ChatPanel.module.css`**

```css
.panel { display: flex; flex-direction: column; height: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
.messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.message { align-self: flex-end; max-width: 85%; background: var(--electric); color: white; padding: 8px 12px; border-radius: 12px; }
.composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
.input { flex: 1; padding: 10px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); }
.preview { padding: 10px 18px; background: var(--electric); color: white; border: none; border-radius: 8px; }
.preview:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.*
git commit -m "feat: add agent chat panel"
```

---

### Task 7: CandidateCard (continuity scorecard)

**Files:**
- Create: `frontend/src/components/CandidateCard.tsx`, `frontend/src/components/CandidateCard.module.css`
- Test: `frontend/src/components/CandidateCard.test.tsx`

**Interfaces:**
- Consumes: `Candidate` from `types.ts`.
- Produces: `CandidateCard({ candidate, onApprove, onTryAgain }: { candidate: Candidate; onApprove: () => void; onTryAgain: () => void })`. Renders the new text, a "✓ Continuity checked" badge when `continuity.passed`, the four metric bars in fixed order (each labeled + valued, glowing cyan when `>= 0.8` else amber), the warnings, and Approve / Try again buttons. Approve is disabled when `!continuity.passed`.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CandidateCard } from './CandidateCard'
import type { Candidate } from '../types'

const PASSING: Candidate = {
  plan: { selection: { start: 0.4, end: 1.3 }, new_text: '30% off', voice_profile_id: 'speaker-1' },
  audio_ref: 'audio://x', frames_ref: 'frames://x',
  continuity: { voice_match: 0.95, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94, passed: true, warnings: [] },
}

const FAILING: Candidate = {
  ...PASSING,
  continuity: { voice_match: 0.40, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94, passed: false, warnings: ['Low voice identity (0.40)'] },
}

describe('CandidateCard', () => {
  it('shows the new text, the pass badge, and all four metrics', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} />)
    expect(screen.getByText('30% off')).toBeInTheDocument()
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()
    expect(screen.getByText(/voice/i)).toBeInTheDocument()
    expect(screen.getByText(/prosody/i)).toBeInTheDocument()
    expect(screen.getByText(/audio/i)).toBeInTheDocument()
    expect(screen.getByText(/lip-?sync/i)).toBeInTheDocument()
  })

  it('fires onApprove when passing and Approve is clicked', async () => {
    const onApprove = vi.fn()
    render(<CandidateCard candidate={PASSING} onApprove={onApprove} onTryAgain={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('disables Approve and surfaces warnings when continuity fails', () => {
    render(<CandidateCard candidate={FAILING} onApprove={() => {}} onTryAgain={() => {}} />)
    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByText(/low voice identity/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/CandidateCard.test.tsx`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `CandidateCard.tsx`**

```tsx
import type { Candidate, ContinuityReport } from '../types'
import styles from './CandidateCard.module.css'

const METRICS: { key: keyof ContinuityReport; label: string }[] = [
  { key: 'voice_match', label: 'Voice identity' },
  { key: 'prosody', label: 'Prosody & energy' },
  { key: 'audio_integration', label: 'Audio integration' },
  { key: 'lip_sync', label: 'Lip-sync' },
]

const THRESHOLD = 0.8

export function CandidateCard({
  candidate, onApprove, onTryAgain,
}: { candidate: Candidate; onApprove: () => void; onTryAgain: () => void }) {
  const c = candidate.continuity
  return (
    <div className={styles.card}>
      <div className={styles.newText}>{candidate.plan.new_text}</div>

      {c.passed ? (
        <div className={styles.badge}>✓ Continuity checked</div>
      ) : (
        <div className={styles.badgeFail}>Continuity below threshold</div>
      )}

      <div className={styles.metrics}>
        {METRICS.map(({ key, label }) => {
          const value = c[key] as number
          const ok = value >= THRESHOLD
          return (
            <div key={key} className={styles.metric}>
              <span className={styles.metricLabel}>{label}</span>
              <div className={styles.barTrack}>
                <div
                  className={ok ? styles.barFillOk : styles.barFillWarn}
                  style={{ width: `${value * 100}%` }}
                />
              </div>
              <span className={styles.metricValue}>{value.toFixed(2)}</span>
            </div>
          )
        })}
      </div>

      {c.warnings.length > 0 && (
        <ul className={styles.warnings}>
          {c.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      <div className={styles.actions}>
        <button className={styles.approve} onClick={onApprove} disabled={!c.passed}>
          Approve
        </button>
        <button className={styles.tryAgain} onClick={onTryAgain}>Try again</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `CandidateCard.module.css`**

```css
.card { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.newText { font-size: 18px; font-weight: 600; }
.badge { align-self: flex-start; color: var(--pass); border: 1px solid var(--pass); border-radius: 999px; padding: 2px 10px; font-size: 12px; box-shadow: 0 0 12px rgba(34,211,238,0.4); }
.badgeFail { align-self: flex-start; color: var(--warn); border: 1px solid var(--warn); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.metrics { display: flex; flex-direction: column; gap: 8px; }
.metric { display: grid; grid-template-columns: 120px 1fr 40px; gap: 8px; align-items: center; font-size: 12px; }
.metricLabel { color: var(--muted); }
.barTrack { height: 8px; background: var(--surface); border-radius: 4px; overflow: hidden; }
.barFillOk { height: 100%; background: var(--cyan); box-shadow: 0 0 10px var(--cyan); transition: width 400ms ease; }
.barFillWarn { height: 100%; background: var(--warn); transition: width 400ms ease; }
.metricValue { text-align: right; color: var(--text); }
.warnings { margin: 0; padding-left: 18px; color: var(--warn); font-size: 12px; }
.actions { display: flex; gap: 8px; }
.approve { flex: 1; padding: 10px; background: var(--electric); color: white; border: none; border-radius: 8px; box-shadow: 0 0 16px rgba(46,107,255,0.4); }
.approve:disabled { background: var(--border); color: var(--muted); box-shadow: none; cursor: not-allowed; }
.tryAgain { padding: 10px 16px; background: transparent; color: var(--text); border: 1px solid var(--border); border-radius: 8px; }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/CandidateCard.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CandidateCard.*
git commit -m "feat: add continuity scorecard candidate card"
```

---

### Task 8: ExportBar

**Files:**
- Create: `frontend/src/components/ExportBar.tsx`, `frontend/src/components/ExportBar.module.css`
- Test: `frontend/src/components/ExportBar.test.tsx`

**Interfaces:**
- Consumes: `Segment` from `types.ts`.
- Produces: `ExportBar({ segments, onExport }: { segments: Segment[]; onExport: () => void })`. Renders an Export button that calls `onExport`; when `segments` is non-empty, renders a horizontal strip of proportionally-sized blocks, each with `data-kind` = `original`/`edited`.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExportBar } from './ExportBar'
import type { Segment } from '../types'

const SEGMENTS: Segment[] = [
  { start: 0, end: 0.4, kind: 'original', ref: 'ad.mp4' },
  { start: 0.4, end: 1.3, kind: 'edited', ref: 'frames://e1' },
  { start: 1.3, end: 3, kind: 'original', ref: 'ad.mp4' },
]

describe('ExportBar', () => {
  it('calls onExport when clicked', async () => {
    const onExport = vi.fn()
    render(<ExportBar segments={[]} onExport={onExport} />)
    await userEvent.click(screen.getByRole('button', { name: /export/i }))
    expect(onExport).toHaveBeenCalledOnce()
  })

  it('renders one strip block per segment', () => {
    render(<ExportBar segments={SEGMENTS} onExport={() => {}} />)
    expect(screen.getAllByTestId('segment')).toHaveLength(3)
    const edited = screen.getAllByTestId('segment').filter(
      (el) => el.getAttribute('data-kind') === 'edited',
    )
    expect(edited).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/ExportBar.test.tsx`
Expected: FAIL — cannot find module.

- [ ] **Step 3: Write `ExportBar.tsx`**

```tsx
import type { Segment } from '../types'
import styles from './ExportBar.module.css'

export function ExportBar({ segments, onExport }: { segments: Segment[]; onExport: () => void }) {
  const total = segments.length ? segments[segments.length - 1].end : 0
  return (
    <div className={styles.bar}>
      <button className={styles.export} onClick={onExport}>Export</button>
      {segments.length > 0 && (
        <div className={styles.strip}>
          {segments.map((s, i) => (
            <div
              key={i}
              data-testid="segment"
              data-kind={s.kind}
              className={s.kind === 'edited' ? styles.edited : styles.original}
              style={{ width: `${((s.end - s.start) / total) * 100}%` }}
              title={`${s.kind} ${s.start}–${s.end}s`}
            />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Write `ExportBar.module.css`**

```css
.bar { display: flex; align-items: center; gap: 12px; }
.export { padding: 10px 20px; background: transparent; color: var(--cyan); border: 1px solid var(--cyan); border-radius: 8px; box-shadow: 0 0 12px rgba(34,211,238,0.3); }
.strip { flex: 1; height: 20px; display: flex; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
.original { background: var(--surface); }
.edited { background: var(--cyan); box-shadow: inset 0 0 12px rgba(34,211,238,0.6); }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/ExportBar.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ExportBar.*
git commit -m "feat: add export bar with segment manifest strip"
```

---

### Task 9: App wiring, sample asset, and full-journey integration test

**Files:**
- Create: `frontend/src/App.tsx`, `frontend/src/App.module.css`, `frontend/public/sample-ad.mp4`
- Modify: `frontend/src/main.tsx` (render `<App/>`)
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: everything above — `ConsentGate`, `LoadScreen`, `Player`, `Timeline`, `ChatPanel`, `CandidateCard`, `ExportBar`, and the `api.ts` functions (`createProject`, `previewEdit`, `approveEdit`, `exportProject`).
- Produces: `App()` — the root state machine.

Constants used by `App`: sample filename `'sample-ad.mp4'`, sample duration `2.3`, sample src `'/sample-ad.mp4'`, default `voice_profile_id` `'speaker-1'`.

- [ ] **Step 1: Add the sample video asset**

Place any short (~2–3s) clip at `frontend/public/sample-ad.mp4`. If you don't have one, generate a placeholder with ffmpeg:
```bash
ffmpeg -f lavfi -i "color=c=0x0d1a2b:s=1280x720:d=2.3" \
  -vf "drawtext=text='sample ad':fontcolor=0x22D3EE:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2" \
  -pix_fmt yuv420p frontend/public/sample-ad.mp4
```
(If ffmpeg is unavailable, any small mp4 works; the Player degrades to its gradient stage if the file is missing.)

- [ ] **Step 2: Write the failing integration test `App.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const PROJECT = {
  project_id: 'p1',
  transcript: [
    { text: 'Get', start: 0.0, end: 0.4 },
    { text: '20%', start: 0.4, end: 0.9 },
    { text: 'off', start: 0.9, end: 1.3 },
  ],
}
const CANDIDATE = {
  plan: { selection: { start: 0.4, end: 0.9 }, new_text: '30% off', voice_profile_id: 'speaker-1' },
  audio_ref: 'audio://x', frames_ref: 'frames://x',
  continuity: { voice_match: 0.95, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94, passed: true, warnings: [] },
}

function routeFetch() {
  return vi.fn(async (url: string) => {
    const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' } as Response)
    if (url.endsWith('/projects')) return ok(PROJECT)
    if (url.endsWith('/edits/preview')) return ok(CANDIDATE)
    if (url.endsWith('/edits')) return ok({ edit_id: 'e1', continuity: CANDIDATE.continuity })
    if (url.endsWith('/export')) return ok({ segments: [
      { start: 0, end: 0.4, kind: 'original', ref: 'sample-ad.mp4' },
      { start: 0.4, end: 0.9, kind: 'edited', ref: 'frames://x' },
      { start: 0.9, end: 2.3, kind: 'original', ref: 'sample-ad.mp4' },
    ] })
    throw new Error(`unexpected url ${url}`)
  })
}

beforeEach(() => { vi.restoreAllMocks() })

describe('App full journey', () => {
  it('runs consent → load → select → preview → approve → export', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)

    // Consent
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /continue/i }))

    // Load
    await user.click(screen.getByRole('button', { name: /load sample ad/i }))
    await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())

    // Select a word
    await user.click(screen.getByText('20%'))

    // Prompt + preview
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))
    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())

    // Approve
    await user.click(screen.getByRole('button', { name: /approve/i }))

    // Export
    await user.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(screen.getAllByTestId('segment')).toHaveLength(3))
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — cannot find module `./App` (or the template's default App has no such flow).

- [ ] **Step 4: Write `App.tsx`**

```tsx
import { useState } from 'react'
import { ConsentGate } from './components/ConsentGate'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { CandidateCard } from './components/CandidateCard'
import { ExportBar } from './components/ExportBar'
import { createProject, previewEdit, approveEdit, exportProject, ApiError } from './api'
import type { Word, Selection, Candidate, Segment } from './types'
import styles from './App.module.css'

const SAMPLE = { filename: 'sample-ad.mp4', duration: 2.3, src: '/sample-ad.mp4' }
const VOICE = 'speaker-1'

type Stage = 'consent' | 'load' | 'editor'

export default function App() {
  const [stage, setStage] = useState<Stage>('consent')
  const [loading, setLoading] = useState(false)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<Word[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [messages, setMessages] = useState<string[]>([])
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [lastPrompt, setLastPrompt] = useState('')
  const [segments, setSegments] = useState<Segment[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const project = await createProject(SAMPLE.filename, SAMPLE.duration)
      setProjectId(project.project_id)
      setTranscript(project.transcript)
      setStage('editor')
    } catch {
      setError('Could not load the project.')
    } finally {
      setLoading(false)
    }
  }

  const runPreview = async (prompt: string) => {
    if (!projectId || !selection) return
    setMessages((m) => [...m, prompt])
    setLastPrompt(prompt)
    setCandidate(null)
    setError(null)
    try {
      const c = await previewEdit(projectId, {
        prompt, start: selection.start, end: selection.end, voice_profile_id: VOICE,
      })
      setSelection(c.plan.selection) // reflect the backend's snapped range
      setCandidate(c)
    } catch {
      setError('Preview failed. Try again.')
    }
  }

  const approve = async () => {
    if (!projectId || !candidate) return
    setError(null)
    try {
      await approveEdit(projectId, {
        prompt: lastPrompt,
        start: candidate.plan.selection.start,
        end: candidate.plan.selection.end,
        voice_profile_id: VOICE,
      })
      setCandidate(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError('Continuity check failed — cannot ship this edit.')
      } else {
        setError('Approve failed.')
      }
    }
  }

  const runExport = async () => {
    if (!projectId) return
    try {
      const manifest = await exportProject(projectId)
      setSegments(manifest.segments)
    } catch {
      setError('Export failed.')
    }
  }

  if (stage === 'consent') return <ConsentGate onConfirm={() => setStage('load')} />
  if (stage === 'load') return <LoadScreen onLoad={load} loading={loading} />

  return (
    <div className={styles.app}>
      <div className={styles.left}>
        <Player src={SAMPLE.src} duration={SAMPLE.duration} currentTime={currentTime} onSeek={setCurrentTime} />
        <Timeline
          words={transcript}
          duration={SAMPLE.duration}
          selection={selection}
          currentTime={currentTime}
          onSelect={setSelection}
        />
        <ExportBar segments={segments} onExport={runExport} />
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.right}>
        <ChatPanel messages={messages} canSubmit={selection !== null} onSubmit={runPreview}>
          {candidate && (
            <CandidateCard
              candidate={candidate}
              onApprove={approve}
              onTryAgain={() => setCandidate(null)}
            />
          )}
        </ChatPanel>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Write `App.module.css`**

```css
.app { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; padding: 20px; height: 100vh; }
.left { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.right { min-height: 0; }
.error { color: var(--warn); border: 1px solid var(--warn); border-radius: 8px; padding: 8px 12px; font-size: 13px; }
```

- [ ] **Step 6: Update `frontend/src/main.tsx` to render `App`**

Ensure it reads (adjust to the template's existing imports):
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/theme.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```
Delete the template's leftover `frontend/src/App.css` and default demo assets if present, and remove any stale `App.test` the template shipped.

- [ ] **Step 7: Run the integration test**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `cd frontend && npm test`
Expected: ALL tests pass (Tasks 0–9).

- [ ] **Step 9: Manual smoke against the real backend**

In one terminal: `cd backend && .venv/bin/python -m uvicorn app.api.main:app --port 8000`.
In another: `cd frontend && npm run dev`, open the shown URL, and click through consent → load → select "20%" → prompt `change "20% off" to "30% off"` → Preview → Approve → Export. Confirm the scorecard passes and the export strip shows original/edited/original.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/App.* frontend/src/main.tsx frontend/public/sample-ad.mp4
git commit -m "feat: wire Voltage editor end-to-end"
```

---

## Self-Review Notes

- **Spec coverage:** consent gate (Task 2), load/ingest via `POST /projects` (Task 3, 9), player play/pause + scrubber (Task 4), timeline selection + glowing region + playhead + snapping reflected from backend (Task 5, 9), agent chat + prompt (Task 6), continuity scorecard candidate with four metrics + warnings + approve/iterate (Task 7), export manifest strip (Task 8), full journey + 422 failure handling (Task 9). Voltage palette + signature glows applied across component CSS. Deferred items (async polling, backend consent, real media) are intentionally not implemented, matching spec §10.
- **Type consistency:** `EditRequest{prompt,start,end,voice_profile_id}`, `Candidate.plan.selection`, `ContinuityReport` keys (`voice_match`/`prosody`/`audio_integration`/`lip_sync`), and the four API functions are used identically across `api.ts`, every component, and `App`. Metric order and the `0.8` threshold are fixed in Global Constraints and reused in Task 7.
- **No placeholders:** every step has runnable code/commands and expected output. The sample-video step provides a concrete ffmpeg fallback and a graceful-degradation path.
- **Proxy correctness:** the client calls `/api/...`; Vite strips `/api` so the backend's `/projects...` routes match. Tests stub `fetch` and assert the `/api/...` URLs directly, so they don't depend on the proxy.
