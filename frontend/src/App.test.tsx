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
  passed: true, warnings: [] as string[], measured: [] as string[],
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

const RENDER = { kind: 'video', sha256: 'r'.repeat(64), duration: 2.3, container: 'mp4' }

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
  return vi.fn(async (url: string, _init?: RequestInit) => {
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
    if (url.endsWith('/export')) return ok({ segments: SEGMENTS, render: RENDER })
    if (url.endsWith('/usage')) {
      return ok({ spent_usd: 0.01, ceiling_usd: 2, voice_characters: 7,
        voice_characters_ceiling: 2000, lines: [] })
    }
    if (url.endsWith('/projects')) return ok(_init?.method === 'POST' ? PROJECT : { projects: [] })
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
    await waitFor(() => expect(screen.getByTestId('spend')).toHaveTextContent('voice 7 / 2,000'))

    await user.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() => expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(screen.getAllByTestId('segment')).toHaveLength(3))
    const link = screen.getByRole('link', { name: /download mp4/i })
    expect(link).toHaveAttribute('href', `/api/projects/p1/artifacts/${'r'.repeat(64)}`)
    expect(link).toHaveAttribute('download', 'sample-ad-edited.mp4')
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

    const upload = f.mock.calls.find(
      ([url, init]) => String(url).endsWith('/projects') && init?.method === 'POST')
    expect(upload).toBeDefined()
    const body = upload?.[1]?.body as FormData
    expect(body.get('consent')).toBe('true')
  })

  it('surfaces the backend refusal if generation is attempted without consent', async () => {
    const forbidden = {
      ok: false, status: 403,
      json: async () => ({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
      text: async () => JSON.stringify({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
    } as Response

    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/usage')) return forbidden
      if (url.endsWith('/edits/preview')) return forbidden
      if (url.endsWith('/projects')) return ok(init?.method === 'POST' ? PROJECT : { projects: [] })
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

describe('App conversation (Phase 8)', () => {
  /** Serves the given job results in turn, recording each preview request. */
  function conversation(results: unknown[]) {
    const bodies: Record<string, unknown>[] = []
    let turn = -1
    const base = routeFetch()
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/preview')) {
        turn += 1
        bodies.push(JSON.parse(String(init?.body)))
        return ok(JOB_ACCEPTED)
      }
      if (url.includes('/jobs/')) return ok({ ...JOB_DONE, result: results[turn] })
      return base(url, init)
    })
    vi.stubGlobal('fetch', fetchMock)
    return bodies
  }

  it('shows a reply for a request the editor cannot do', async () => {
    conversation([{ type: 'reply', text: 'This editor only changes spoken dialogue.' }])
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'make the background white{Enter}')

    await waitFor(() =>
      expect(screen.getByText('This editor only changes spoken dialogue.')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('asks how to place the line, then re-sends the request with the choice', async () => {
    const question = {
      type: 'question',
      question: 'The line is 0.30s but the selection is 0.50s. How should it fill the selection?',
      text: '30% off',
      mix: 'layer',
      options: [
        { label: "Start at the selection's start", fit: 'start', mix: null, warning: null },
        { label: 'Slow it down to fill', fit: 'stretch', mix: null, warning: 'It will sound dragged.' },
      ],
    }
    const bodies = conversation([question, CANDIDATE])
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'say 30% off{Enter}')
    await waitFor(() => expect(screen.getByText(question.question)).toBeInTheDocument())
    expect(screen.getByText('It will sound dragged.')).toBeInTheDocument()

    await user.click(screen.getByText('Slow it down to fill'))

    await waitFor(() => expect(screen.getByText(/continuity checked/i)).toBeInTheDocument())
    expect(bodies[1]).toMatchObject({
      prompt: 'say 30% off', text: '30% off', fit: 'stretch', mix: 'layer', start: 0.4, end: 0.9,
    })
    // The server keeps the chat; the answer carries only how to show it.
    expect(bodies[1].display).toBe('Slow it down to fill')
    expect(bodies[0]).not.toHaveProperty('display')
    // The choice shows in the chat as the user's reply.
    expect(screen.getAllByText('Slow it down to fill').length).toBeGreaterThan(0)
  })
})

describe('App playback after approval', () => {
  it('renders the approved edit and plays it, with the original a click away', async () => {
    const fetchMock = routeFetch()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"{Enter}')
    await waitFor(() => expect(screen.getByText(/continuity checked/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /approve/i }))

    const video = () => container.querySelector('video') as HTMLVideoElement
    const renderUrl = `/api/projects/p1/artifacts/${'r'.repeat(64)}`
    await waitFor(() => expect(video().getAttribute('src')).toBe(renderUrl))
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/export'))).toBe(true)
    expect(screen.getByRole('button', { name: 'Edited' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Original' }))
    expect(video().getAttribute('src')).toBe(`/api/projects/p1/artifacts/${'s'.repeat(64)}`)
  })
})

describe('App projects (Phase 9a)', () => {
  const DETAIL = {
    ...PROJECT,
    created_at: '2026-09-26T08:00:00Z',
    edits: [{ edit_id: 'e1', candidate_id: 'c1', new_text: '30% off',
      selection: { start: 0.4, end: 0.9 }, mix: 'replace', overridden: false }],
    messages: [
      { role: 'user', text: 'change "20% off" to "30% off"' },
      { role: 'assistant', text: 'Earlier reply.' },
    ],
  }

  function withProjects() {
    const base = routeFetch()
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects') && init?.method !== 'POST') {
        return ok({ projects: [{ project_id: 'p1', filename: 'sample-ad.mp4', duration: 2.3,
          created_at: '2026-09-26T08:00:00Z', edits: 1 }] })
      }
      if (url.endsWith('/projects/p1') && init?.method === 'DELETE') {
        return { ok: true, status: 204, text: async () => '' } as Response
      }
      if (url.endsWith('/projects/p1')) return ok(DETAIL)
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    return f
  }

  async function toLoadScreen(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /continue/i }))
  }

  it('reopens a project with its chat, and plays its approved edits', async () => {
    const f = withProjects()
    const user = userEvent.setup()
    const { container } = render(<App />)
    await toLoadScreen(user)

    await user.click(await screen.findByText('sample-ad.mp4'))

    await waitFor(() => expect(screen.getByText('Earlier reply.')).toBeInTheDocument())
    expect(screen.getByText('20%')).toBeInTheDocument()
    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement)
      .getAttribute('src')).toBe(`/api/projects/p1/artifacts/${'r'.repeat(64)}`))
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/export'))).toBe(true)
  })

  it('deletes a project after asking once more', async () => {
    const f = withProjects()
    const user = userEvent.setup()
    render(<App />)
    await toLoadScreen(user)

    await user.click(await screen.findByRole('button', { name: 'Delete sample-ad.mp4' }))
    await user.click(screen.getByRole('button', { name: /delete for good/i }))

    await waitFor(() => expect(f.mock.calls.some(
      ([url, init]) => String(url).endsWith('/projects/p1') && init?.method === 'DELETE')).toBe(true))
  })

  it('goes back to the project list from the editor', async () => {
    withProjects()
    const user = userEvent.setup()
    render(<App />)
    await toLoadScreen(user)
    await user.click(await screen.findByText('sample-ad.mp4'))
    await screen.findByText('Earlier reply.')

    await user.click(screen.getByRole('button', { name: /projects/i }))

    expect(await screen.findByText(/your projects/i)).toBeInTheDocument()
  })
})
