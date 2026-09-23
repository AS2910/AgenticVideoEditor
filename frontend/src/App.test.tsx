import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const SOURCE_MEDIA = {
  kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4',
}

const PROJECT = {
  project_id: 'p1',
  filename: 'sample-ad.mp4',
  duration: 2.3,
  media: SOURCE_MEDIA,
  transcript: [
    { text: 'Get', start: 0.0, end: 0.4 },
    { text: '20%', start: 0.4, end: 0.9 },
    { text: 'off', start: 0.9, end: 1.3 },
  ],
}

const PASSING_CONTINUITY = {
  voice_match: 0.95, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94,
  passed: true, warnings: [] as string[],
}

const AUDIO = { kind: 'audio', sha256: 'a'.repeat(64), duration: 0.5, container: 'wav' }
const FRAMES = { kind: 'video', sha256: 'f'.repeat(64), duration: 0.5, container: 'mp4' }

const CANDIDATE = {
  candidate_id: 'c1',
  plan: { selection: { start: 0.4, end: 0.9 }, new_text: '30% off', voice_profile_id: 'speaker-1' },
  audio: AUDIO,
  frames: FRAMES,
  continuity: PASSING_CONTINUITY,
}

const SEGMENTS = [
  { start: 0, end: 0.4, kind: 'original', ref: 'sample-ad.mp4', artifact: null },
  { start: 0.4, end: 0.9, kind: 'edited', ref: FRAMES.sha256, artifact: FRAMES },
  { start: 0.9, end: 2.3, kind: 'original', ref: 'sample-ad.mp4', artifact: null },
]

const ok = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response

const JOB_ACCEPTED = {
  job_id: 'j1', kind: 'preview', project_id: 'p1',
  status: 'queued', progress: 0, step: 'Queued',
  attempts: 0, result: null, error: null,
}

const JOB_DONE = {
  ...JOB_ACCEPTED, status: 'succeeded', progress: 1, step: 'Ready', result: CANDIDATE,
}

const JOB_FAILED = {
  ...JOB_ACCEPTED, status: 'failed', progress: 0.55, step: 'Failed',
  attempts: 3, error: 'Generation failed after several attempts. Try again.',
}

/** Routes by URL. `approveStatus` forces the 422 branch; `job` overrides the
 *  polled job so a test can exercise the failure path. */
function routeFetch(approveStatus = 200, job: unknown = JOB_DONE) {
  return vi.fn(async (url: string) => {
    if (url.includes('/jobs/')) return ok(job)
    if (url.endsWith('/edits/preview')) return ok(JOB_ACCEPTED)
    if (url.endsWith('/edits')) {
      if (approveStatus !== 200) {
        return {
          ok: false,
          status: approveStatus,
          json: async () => ({ detail: 'continuity check failed' }),
          text: async () => 'continuity check failed',
        } as Response
      }
      return ok({ edit_id: 'e1', continuity: PASSING_CONTINUITY })
    }
    if (url.endsWith('/export')) return ok({ segments: SEGMENTS })
    if (url.endsWith('/projects')) return ok(PROJECT)
    // The sample clip is fetched from /public, then uploaded like any file.
    if (url.endsWith('/sample-ad.mp4')) {
      return { ok: true, status: 200, blob: async () => new Blob(['mp4-bytes']) } as Response
    }
    throw new Error(`unexpected url ${url}`)
  })
}

/** consent -> load -> editor, leaving the app on the editor screen. */
async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: /continue/i }))
  await user.click(screen.getByRole('button', { name: /sample ad/i }))
  await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())
}

beforeEach(() => { vi.restoreAllMocks() })

describe('App full journey', () => {
  it('runs consent → load → select → preview → approve → export', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)

    await reachEditor(user)

    // Select a word, then prompt
    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() => expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(screen.getAllByTestId('segment')).toHaveLength(3))
  })

  it('shows the job step and progress while generation runs', async () => {
    // A job that never finishes, so the waiting state stays on screen.
    const pending = { ...JOB_ACCEPTED, status: 'running', progress: 0.55, step: 'Matching mouth movement' }
    vi.stubGlobal('fetch', routeFetch(200, pending))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() =>
      expect(screen.getByText(/matching mouth movement/i)).toBeInTheDocument())
    expect(screen.getByTestId('progress-bar')).toHaveStyle({ width: '55%' })
    // No candidate yet — the scorecard must not appear early.
    expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument()
  })

  it('surfaces the job error when generation fails', async () => {
    vi.stubGlobal('fetch', routeFetch(200, JOB_FAILED))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() =>
      expect(screen.getByText(/failed after several attempts/i)).toBeInTheDocument())
    // The waiting indicator is cleared rather than left spinning forever.
    expect(screen.queryByTestId('generating')).not.toBeInTheDocument()
  })

  it('sends the confirmed consent along with the upload', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    const upload = f.mock.calls.find(([url]) => String(url).endsWith('/projects'))
    expect((upload![1].body as FormData).get('consent')).toBe('true')
  })

  it('surfaces the backend refusal if generation is attempted without consent', async () => {
    const forbidden = {
      ok: false, status: 403,
      json: async () => ({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
      text: async () => JSON.stringify({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
    } as Response

    const f = vi.fn(async (url: string) => {
      if (url.endsWith('/edits/preview')) return forbidden
      if (url.endsWith('/projects')) return ok(PROJECT)
      if (url.endsWith('/sample-ad.mp4')) {
        return { ok: true, status: 200, blob: async () => new Blob(['mp4']) } as Response
      }
      throw new Error(`unexpected url ${url}`)
    })
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() =>
      expect(screen.getByText(/right to edit and clone/i)).toBeInTheDocument())
  })

  it('gates the editor behind consent', () => {
    vi.stubGlobal('fetch', routeFetch())
    render(<App />)
    expect(screen.getByText(/right to edit and clone the speaker/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load sample ad/i })).not.toBeInTheDocument()
  })

  it('cannot preview until a selection exists', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.type(screen.getByRole('textbox'), 'change the offer')
    expect(screen.getByRole('button', { name: /preview/i })).toBeDisabled()
  })

  it('surfaces a continuity failure when approve is rejected with 422', async () => {
    vi.stubGlobal('fetch', routeFetch(422))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))
    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /approve/i }))

    // Honest failure: message shown and the candidate is NOT silently dropped.
    await waitFor(() =>
      expect(screen.getByText(/continuity check failed/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('30% off')).toBeInTheDocument()
  })

  it('reflects the backend snapped selection on the timeline', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get')) // 0.0–0.4
    await user.type(screen.getByRole('textbox'), 'change it')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    // Backend returns 0.4–0.9; the timeline region must follow it.
    await waitFor(() => {
      const region = screen.getByTestId('selection-region')
      expect(region.style.left).toMatch(/^17\.39/) // 0.4 / 2.3
    })
  })
})
