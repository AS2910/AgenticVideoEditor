import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const SOURCE_MEDIA = {
  kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4',
}

const PROJECT = {
  statements: [{ text: 'Get 20% off today only.', start: 0.0, end: 2.3 }],
  consent: { granted_at: '2026-09-26T08:00:00Z' },
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

const PLAN_ITEM = {
  item_id: 'i1', selection: { start: 0, end: 2.3 }, old_text: 'Get 20% off today only.',
  new_text: 'Get 30% off today only.', speaker: null, mix: 'replace', reason: 'The offer is said here.',
  kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null,
  question: null, error: null, note: null, progress: null,
}
const PLAN = {
  type: 'plan', plan_id: 'plan1', goal: 'make it 30% off', summary: 'I read 1 line. One change does it.',
  mode: 'ask', status: 'proposed', created_at: '2026-10-02T10:00:00Z',
  estimate: { items: 1, voice_characters: 23, usd: 0.0069, seconds: 12 },
  findings: ['One line, one speaker.', 'The offer is said once, at 0:00.'], question: null, spend_usd: 0.01,
  log: [{ at: '2026-10-02T10:00:00Z', text: 'Read your goal and all 1 lines', detail: 'Claude' }],
  items: [PLAN_ITEM],
}
const PLAN_REVISED = { ...PLAN, summary: 'Left the change out.', items: [{ ...PLAN_ITEM, enabled: false }],
  log: [...PLAN.log, { at: '2026-10-04T10:00:00Z', text: 'You said: not that one', detail: '' }] }
const PLAN_CLARIFYING = { ...PLAN, status: 'clarifying',
  question: { text: 'Who speaks for the brand?', options: ['The Shopkeeper', 'The Customer'], guess: 'The Shopkeeper' } }
const BRIAN_TAKE = { ...CANDIDATE, plan: { ...CANDIDATE.plan, voice_profile_id: 'nPczCjzI2devNBz1zQrb' } }
const PLAN_DONE = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'ready', candidate: BRIAN_TAKE }] }
const PLAN_APPROVED = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'approved', candidate: BRIAN_TAKE, edit_id: 'e1' }],
  log: [...PLAN.log, { at: '2026-10-02T10:01:00Z', text: 'Rendered the edited video', detail: '$0.02 in total' }] }

const READING = { opening: 'One person, one line. The offer is said once, at 0:00.', roles: [] }

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
    if (url.endsWith('/revert')) return ok({ edit_id: 'e1', reverted: true })
    if (url.endsWith('/lines/remove')) return ok({ edit_id: 'e7', candidate_id: 'c7', selection: { start: 0, end: 2.3 }, mix: 'remove' })
    if (url.endsWith('/lines/shift')) {
      return ok({ edit_id: 'e9', removed_edit_id: 'e8', candidate: CANDIDATE, from: { start: 0, end: 2.3 }, selection: { start: 1.0, end: 2.3 }, mix: 'layer' })
    }
    if (url.endsWith('/settings')) {
      return ok({ settings: { long_lines: JSON.parse(String(_init?.body)).long_lines } })
    }
    if (url.endsWith('/lines/reword')) {
      return ok({ text: 'Get 30% off today.', selection: { start: 0, end: 2.3 } })
    }
    if (url.endsWith('/auth/me')) return ok({ mode: 'off', user: null })
    if (url.endsWith('/reading')) return ok(READING)
    if (url.endsWith('/plans')) return ok(PLAN)
    if (/\/plans\/plan1$/.test(url)) return ok(PLAN)
    if (url.includes('/plans/plan1/items/') && _init?.method === 'PUT') return ok(PLAN)
    if (url.endsWith('/plans/plan1/run') || url.endsWith('/answer') || url.endsWith('/redo')) return ok({ ...JOB_ACCEPTED, kind: 'plan' })
    if (url.endsWith('/plans/plan1/clarify')) return ok(PLAN)
    if (url.endsWith('/plans/plan1/approve')) {
      return ok({ approved: [{ item_id: 'i1', edit_id: 'e1', overridden: false }], skipped: [],
        export: { segments: SEGMENTS, render: RENDER }, plan: PLAN_APPROVED })
    }
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
    if (url.endsWith('/voices')) {
      return ok({ default: 'EXAVITQu4vr4xnSDxMaL', voices: [
        { voice_id: 'EXAVITQu4vr4xnSDxMaL', name: 'Sarah', description: '', gender: 'female', accent: 'american', age: null },
        { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: 'american', age: null },
      ] })
    }
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

/** load -> the goal stage, where Voltage has read the clip. */
async function reachGoal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /sample ad/i }))
  await screen.findByText('What should this video say?')
}

/** load -> goal -> editor, hands-on, leaving the app on the editor screen. */
async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
  await reachGoal(user)
  await user.click(screen.getByRole('button', { name: /edit a line yourself/i }))
  await screen.findByText('Get 20% off today only.')
  // The word timeline sits behind Precise; most of these tests select a word on it.
  await user.click(screen.getByRole('button', { name: 'Precise' }))
  await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())
}

beforeEach(() => {
  vi.restoreAllMocks()
  window.location.hash = ''   // opening a project writes its id here
})

describe('App full journey', () => {
  it('runs load → select → preview → approve → export', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)

    await reachEditor(user)

    // Select a word, then prompt
    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('spend')).toHaveTextContent('7 of 2,000 voice characters'))

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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() =>
      expect(screen.getByText(/failed after several attempts/i)).toBeInTheDocument())
    // The waiting indicator is cleared rather than left spinning forever.
    expect(screen.queryByTestId('generating')).not.toBeInTheDocument()
  })

  it('uploads without consent, and asks for it in a sentence the first time a voice is made (UX-3)', async () => {
    const base = routeFetch()
    const granted: string[] = []
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects') && init?.method === 'POST') return ok({ ...PROJECT, consent: null })
      if (url.endsWith('/consent')) { granted.push(url); return ok({ project_id: 'p1', consent: { granted_at: '2026-10-04T10:00:00Z' } }) }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    const upload = f.mock.calls.find(([url, init]) => String(url).endsWith('/projects') && init?.method === 'POST')
    expect((upload![1]!.body as FormData).get('consent')).toBe('false')

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    // Nothing is voiced until the question is answered.
    const sheet = await screen.findByRole('dialog')
    expect(sheet).toHaveTextContent("I'll be creating speech in this person's voice")
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/preview'))).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Not yet' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/preview'))).toBe(false)

    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))
    await user.click(await screen.findByRole('button', { name: 'Yes, I have it' }))
    await waitFor(() => expect(granted).toHaveLength(1))
    await waitFor(() => expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/preview'))).toBe(true))
    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())
  })

  it('surfaces the backend refusal if generation is attempted without consent', async () => {
    const forbidden = {
      ok: false, status: 403,
      json: async () => ({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
      text: async () => JSON.stringify({ detail: 'Confirm you have the right to edit and clone this speaker before generating.' }),
    } as Response

    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/me')) return ok({ mode: 'off', user: null })
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() =>
      expect(screen.getByText(/right to edit and clone/i)).toBeInTheDocument())
  })

  it('opens on the load screen; no gate before anything is seen', async () => {
    vi.stubGlobal('fetch', routeFetch())
    render(<App />)
    expect(await screen.findByRole('button', { name: /sample ad/i })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('plans a goal typed with nothing selected, instead of previewing', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change the offer{Enter}')

    await waitFor(() => expect(f.mock.calls.some(([url]) => String(url).endsWith('/plans'))).toBe(true))
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/preview'))).toBe(false)
  })

  it('surfaces a continuity failure when approve is rejected with 422', async () => {
    vi.stubGlobal('fetch', routeFetch(422))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change it')
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'make the background white{Enter}')

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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'say 30% off{Enter}')
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"{Enter}')
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

  async function toLoadScreen(_user: ReturnType<typeof userEvent.setup>) {
    // The app opens on the load screen; nothing gates it (UX-3).
    await screen.findByRole('button', { name: /sample ad/i })
  }

  it('reopens a project with its chat, and plays its approved edits', async () => {
    const f = withProjects()
    const user = userEvent.setup()
    const { container } = render(<App />)
    await toLoadScreen(user)

    await user.click(await screen.findByText('sample-ad.mp4'))

    await waitFor(() => expect(screen.getByText('Earlier reply.')).toBeInTheDocument())
    // The approved edit shows inline: the old words struck, the new ones added.
    expect(screen.getByTestId('revision')).toHaveTextContent('Get 20% 30% off today only.')
    expect(screen.getAllByText('20%').length).toBeGreaterThan(0)
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

    expect(await screen.findByText(/recent/i)).toBeInTheDocument()
  })
})

describe('App editing by transcript and voice (Phase 10)', () => {
  function recording() {
    const bodies: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/preview')) bodies.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    return bodies
  }

  it('previews a statement rewritten in the transcript, in the chosen voice', async () => {
    const bodies = recording()
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await screen.findByRole('option', { name: 'Brian (male, american)' })

    await user.selectOptions(screen.getByRole('combobox'), 'nPczCjzI2devNBz1zQrb')
    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.')
    await user.click(screen.getByRole('button', { name: 'Hear it' }))

    await screen.findByTestId('take')   // under the line, not in the panel
    expect(bodies[0]).toMatchObject({
      text: 'Get 30% off today only.', mix: 'replace', start: 0, end: 2.3,
      voice_profile_id: 'nPczCjzI2devNBz1zQrb',
      display: '“Get 20% off today only.” → “Get 30% off today only.”',
    })
  })

  it('starts in the default voice', async () => {
    const bodies = recording()
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await screen.findByRole('option', { name: 'Brian (male, american)' })

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"{Enter}')

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0].voice_profile_id).toBe('EXAVITQu4vr4xnSDxMaL')
  })
})

describe('App goal stage shows the clip (UX-2)', () => {
  it('reads the clip once, names the speaker by role, and confirms the guess', async () => {
    const base = routeFetch()
    const reads: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects') && init?.method === 'POST') {
        return ok({ ...PROJECT, statements: [{ ...PROJECT.statements[0], speaker: 'A' }],
          speakers: [{ label: 'A', name: 'Speaker A', voice_id: null }] })
      }
      if (url.endsWith('/reading')) { reads.push(url); return ok({ ...READING, roles: [{ label: 'A', role: 'Presenter', why: 'Carries the clip.' }] }) }
      if (url.includes('/speakers/') && init?.method === 'PUT') {
        reads.push('PUT ' + JSON.parse(String(init.body)).name)
        return ok({ speakers: [{ label: 'A', name: 'Presenter', voice_id: null }] })
      }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    expect(await screen.findByText(/The offer is said once, at 0:00\./)).toBeInTheDocument()
    expect(screen.getByTestId('cast')).toHaveTextContent('the Presenter · my guess')
    await user.click(screen.getByRole('button', { name: 'Looks right' }))
    await waitFor(() => expect(reads).toContain('PUT Presenter'))
    // Confirmed: no longer a guess, and the line shows the name.
    await waitFor(() => expect(screen.getByTestId('cast')).not.toHaveTextContent('my guess'))
    expect(screen.getByTestId('cast')).toHaveTextContent('Presenter')
    expect(reads.filter((r) => r.endsWith('/reading'))).toHaveLength(1)
  })
})

describe('App speakers (Phase 11)', () => {
  it('detects speakers, then names them and gives one a voice', async () => {
    const puts: { url: string; body: unknown }[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/speakers/detect')) {
        return ok({ ...PROJECT,
          statements: [{ text: 'Get 20% off today only.', start: 0, end: 2.3, speaker: 'A' }],
          speakers: [{ label: 'A', name: 'Speaker A', voice_id: null }] })
      }
      if (url.includes('/speakers/')) {
        const body = JSON.parse(String(init?.body))
        puts.push({ url, body })
        return ok({ speakers: [{ label: 'A', name: body.name ?? 'Speaker A', voice_id: body.voice_id ?? null }] })
      }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await screen.findByRole('option', { name: 'Brian (male, american)' })

    await user.click(screen.getByRole('button', { name: /detect speakers/i }))
    const name = await screen.findByRole('textbox', { name: 'Name for speaker A' })
    expect(screen.getAllByRole('img', { name: 'Speaker A' }).length).toBeGreaterThan(0)   // on the line

    await user.clear(name)
    await user.type(name, 'Presenter{Enter}')
    await user.selectOptions(screen.getByRole('combobox', { name: /voice for presenter/i }), 'nPczCjzI2devNBz1zQrb')

    expect(puts.map((p) => p.body)).toEqual([{ name: 'Presenter' }, { voice_id: 'nPczCjzI2devNBz1zQrb' }])
  })
})

describe('App reopening from the URL (redesign)', () => {
  it('opens the project named in the URL, skipping the upload screens', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects/p1')) {
        return ok({ ...PROJECT, created_at: '2026-09-26T08:00:00Z', edits: [], messages: [] })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    render(<App />)
    // A fresh project opens on the goal stage; hands-on is one click away.
    expect(await screen.findByText('What should this video say?')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /edit a line yourself/i }))
    expect(await screen.findByText('Get 20% off today only.')).toBeInTheDocument()
  })
})

describe('App agentic editor (Phase 12)', () => {
  const DETAIL = {
    ...PROJECT,
    created_at: '2026-09-26T08:00:00Z',
    settings: { long_lines: 'pause' },
    edits: [
      { edit_id: 'e1', candidate_id: 'c1', new_text: '30% off',
        selection: { start: 0.4, end: 0.9 }, mix: 'replace', overridden: false, reverted: false },
      { edit_id: 'e2', candidate_id: 'c2', new_text: 'gone',
        selection: { start: 0.9, end: 1.3 }, mix: 'replace', overridden: false, reverted: true },
    ],
    messages: [],
  }

  function withDetail(detail: unknown = DETAIL) {
    const base = routeFetch()
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects/p1') && init?.method !== 'DELETE') return ok(detail)
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    return f
  }

  it('reverts an approved edit: the line reads as shot and the original plays', async () => {
    const f = withDetail()
    window.location.hash = 'p1'
    const { container } = render(<App />)
    await screen.findByTestId('revision')
    // A reverted edit from before is not shown.
    expect(screen.queryByText('gone')).not.toBeInTheDocument()
    const video = () => container.querySelector('video') as HTMLVideoElement
    await waitFor(() => expect(video().getAttribute('src')).toBe(`/api/projects/p1/artifacts/${'r'.repeat(64)}`))

    await userEvent.setup().click(screen.getByRole('button', { name: 'Undo' }))

    await waitFor(() => expect(f.mock.calls.some(
      ([url, init]) => String(url).endsWith('/edits/e1/revert') && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(screen.queryByTestId('revision')).not.toBeInTheDocument())
    expect(video().getAttribute('src')).toBe(`/api/projects/p1/artifacts/${'s'.repeat(64)}`)
  })

  it('sends how a long line should be placed, and remembers it for the project', async () => {
    const bodies: Record<string, unknown>[] = []
    const puts: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/preview')) bodies.push(JSON.parse(String(init?.body)))
      if (url.endsWith('/settings')) puts.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    await user.selectOptions(screen.getByRole('combobox', { name: /runs long/i }), 'stretch')
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ text: 'Get 30% off today only.', on_long: 'stretch' })
    expect(puts).toEqual([{ long_lines: 'stretch' }])
  })

  it('says when a take ran into the pause, and can go back to asking', async () => {
    const puts: Record<string, unknown>[] = []
    const ranOn = { ...CANDIDATE, plan: { ...CANDIDATE.plan, selection: { start: 0.4, end: 1.3 } } }
    const base = routeFetch(200, { ...JOB_DONE, result: ranOn })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/settings')) puts.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))   // 0.4–0.9; the take comes back 0.4–1.3
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'say 30% off{Enter}')

    await waitFor(() => expect(screen.getByTestId('placement')).toHaveTextContent('Ran 0.4 s into the pause after it'))
    expect(screen.getByText('Ready to hear')).toBeInTheDocument()   // the line's status
    await user.click(screen.getByRole('button', { name: /ask me each time/i }))
    await waitFor(() => expect(puts).toEqual([{ long_lines: 'ask' }]))
  })

  it('asks Voltage for wording and puts the suggestion in the line', async () => {
    const bodies: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/lines/reword')) bodies.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    await user.click(screen.getByRole('button', { name: /ask voltage for wording/i }))

    await waitFor(() => expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Get 30% off today.'))
    expect(bodies[0]).toMatchObject({ start: 0, end: 2.3, draft: 'Get 20% off today only.' })
  })

  it('shows the line being worked on, then the question it needs you for', async () => {
    const pendingJob = { ...JOB_ACCEPTED, status: 'running', progress: 0.3, step: 'Synthesizing the new line' }
    vi.stubGlobal('fetch', routeFetch(200, pendingJob))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'say 30% off{Enter}')

    await waitFor(() => expect(screen.getByText('Voicing…')).toBeInTheDocument())
  })
})

describe('App the agent (Phase 13)', () => {
  /** The plan routes with state: the plan the server holds, and the job result. */
  function agent(initial: unknown = PLAN, result: unknown = PLAN_DONE) {
    const calls: { url: string; body: unknown }[] = []
    let current = initial
    const base = routeFetch(200, { ...JOB_DONE, kind: 'plan', result })
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      if (url.endsWith('/plans') && init?.method === 'POST') { calls.push({ url, body }); current = initial; return ok(current) }
      if (/\/plans\/plan1$/.test(url)) return ok(current)
      if (url.includes('/plans/plan1/items/') && init?.method === 'PUT') { calls.push({ url, body }); return ok(current) }
      if (url.endsWith('/run') || url.endsWith('/answer') || url.endsWith('/redo')) { calls.push({ url, body }); current = result; return ok({ ...JOB_ACCEPTED, kind: 'plan' }) }
      if (url.endsWith('/clarify')) { calls.push({ url, body }); current = PLAN; return ok(PLAN) }
      if (url.endsWith('/revise')) { calls.push({ url, body }); current = PLAN_REVISED; return ok(PLAN_REVISED) }
      if (url.endsWith('/stop')) { calls.push({ url, body }); current = { ...PLAN, status: 'stopping' }; return ok(current) }
      if (url.endsWith('/approve')) { calls.push({ url, body }); current = PLAN_APPROVED }
      if (url.endsWith('/settings')) calls.push({ url, body })
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    return calls
  }

  it('plans from a goal, waits for Run, voices the plan, then reviews and approves', async () => {
    const calls = agent()
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)

    // W1: the goal, on its own stage.
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off')
    await user.click(screen.getByRole('button', { name: /plan it with me/i }))

    // W3: the plan waits, with what Voltage noticed.
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
    expect(calls[0]).toMatchObject({ body: { goal: 'make it 30% off' } })
    expect(screen.getByRole('checkbox', { name: 'Include the change at 0:00' })).toBeChecked()
    expect(screen.getByText('The offer is said here.')).toBeInTheDocument()
    expect(screen.getByText(/23 voice characters/)).toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()   // on the transcript line
    expect(screen.queryByText(/approve/i)).not.toBeInTheDocument()

    // Go ahead.
    await user.click(screen.getByRole('button', { name: 'Go ahead' }))
    await waitFor(() => expect(screen.getByText("Take · Brian's voice")).toBeInTheDocument())
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/run'))).toBe(true)
    expect(screen.getByText('Ready to hear')).toBeInTheDocument()
    expect(screen.getByTestId('activity')).toHaveTextContent('Read your goal and all 1 lines')
    expect(screen.getByTestId('activity')).toHaveTextContent('$0.01 for this plan')

    // W5: review and ship.
    await user.click(screen.getByRole('button', { name: 'Review 1 ready change' }))
    expect(screen.getByText('One change, ready to ship')).toBeInTheDocument()
    expect(screen.getByTestId('review-row')).toHaveTextContent('Before')
    await user.click(screen.getByRole('button', { name: /ship it/i }))

    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src'))
      .toBe(`/api/projects/p1/artifacts/${'r'.repeat(64)}`))
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/approve'))).toBe(true)
    // UX-3: the sheet says what is in the file.
    const sheet = await screen.findByTestId('ship-sheet')
    expect(sheet).toHaveTextContent('1 line changed. 0:02.3 → 0:02.3, the same length. $0.01 for this plan.')
    expect(sheet).toHaveTextContent('Said “Get 30% off today only.”')
    expect(within(sheet).getByRole('link', { name: 'Download MP4' })).toHaveAttribute('download', 'sample-ad-edited.mp4')
    await user.click(within(sheet).getByRole('button', { name: 'Back to the transcript' }))
    expect(screen.queryByTestId('ship-sheet')).not.toBeInTheDocument()
    expect(screen.getByTestId('activity')).toHaveTextContent('Rendered the edited video')
  })

  it('ships the lines kept and holds the rest; a shipped line can be undone; a variant starts from the plan (UX-3)', async () => {
    const two = { ...PLAN_ITEM, item_id: 'i2', selection: { start: 1.5, end: 2.0 }, new_text: 'Thirty off.', mix: 'over' }
    const done = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'ready', candidate: BRIAN_TAKE }, { ...two, status: 'ready', candidate: BRIAN_TAKE }] }
    const partly = { ...done, items: [{ ...done.items[0], status: 'approved', edit_id: 'e1' }, done.items[1]] }
    const calls = agent(PLAN, done)
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      if (url.endsWith('/approve')) {
        calls.push({ url, body })
        return ok({ approved: [{ item_id: 'i1', edit_id: 'e1', overridden: false }], skipped: [], export: { segments: SEGMENTS, render: RENDER }, plan: partly })
      }
      if (url.endsWith('/revert')) { calls.push({ url, body }); return ok({ edit_id: 'e1', reverted: true }) }
      if (url.endsWith('/variants')) { calls.push({ url, body }); return ok({ ...PROJECT, project_id: 'p2', plan: PLAN }) }
      if (url.endsWith('/projects/p2')) return ok({ ...PROJECT, project_id: 'p2', plan: PLAN, created_at: '2026-10-04T10:00:00Z', edits: [], messages: [] })
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Go ahead' }))
    await user.click(await screen.findByRole('button', { name: 'Review 2 ready changes' }))

    // Hold the second; ship the first.
    expect(screen.getByText('Two changes, ready to ship')).toBeInTheDocument()
    await user.click(within(screen.getByRole('group', { name: 'Keep or hold the change at 0:00' })).getByRole('button', { name: 'Hold' }))
    expect(screen.getByText('1 kept, 1 held as a draft.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Ship 1 of 2' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/approve'))?.body).toEqual({ items: ['i2'] }))

    const sheet = await screen.findByTestId('ship-sheet')
    expect(sheet).toHaveTextContent('held as a draft')
    await user.click(within(sheet).getByRole('button', { name: 'Back to the transcript' }))

    // Review again: one shipped with Undo, one still a draft.
    await user.click(screen.getByRole('button', { name: 'Review 1 ready change' }))
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/edits/e1/revert'))).toBe(true))

    // A variant: the same clip, the plan as a draft, opened as its own project.
    await user.click(screen.getByRole('button', { name: 'Ship it' }))
    await user.click(within(await screen.findByTestId('ship-sheet')).getByRole('button', { name: 'Make a variant' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/projects/p1/variants'))).toBe(true))
    await waitFor(() => expect(window.location.hash).toBe('#p2'))
    expect(await screen.findByRole('checkbox', { name: 'Include the change at 0:00' })).toBeInTheDocument()
  })

  it('unticks and rewords a planned change before running', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await screen.findByRole('checkbox', { name: 'Include the change at 0:00' })

    await user.click(screen.getByRole('checkbox', { name: 'Include the change at 0:00' }))
    const box = screen.getByRole('textbox', { name: 'New wording at 0:00' })
    await user.clear(box)
    await user.type(box, 'Get a third off today only.{Enter}')

    await waitFor(() => expect(calls.filter((c) => c.url.includes('/items/i1'))).toHaveLength(2))
    expect(calls[1].body).toEqual({ enabled: false })
    expect(calls[2].body).toEqual({ new_text: 'Get a third off today only.' })
  })

  it("answers a line that needs you with the agent's shorter line", async () => {
    const needs = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'needs-you', question: {
      type: 'question', question: "The new line runs 1.1 s long and there's no pause after it to run into.", text: 'x', mix: 'replace',
      options: [
        { label: 'Use a shorter line: “30% off today.”', fit: null, mix: null, warning: null, text: '30% off today.' },
        { label: 'Speed it up to fit (1.3× speed)', fit: 'stretch', mix: null, warning: null },
      ] } }] }
    const calls = agent(needs, PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')

    expect(await screen.findByText('Needs you')).toBeInTheDocument()
    expect(screen.getByText('Voltage recommends')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /use a shorter line/i }))

    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/items/i1/answer'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/answer'))?.body).toEqual({ text: '30% off today.' })
    await waitFor(() => expect(screen.getByText('Ready to hear')).toBeInTheDocument())
  })

  it('adds a suggestion to the plan', async () => {
    const suggestion = { ...PLAN_ITEM, item_id: 'i2', kind: 'suggestion', enabled: false, status: 'suggested',
      new_text: 'Get 30% off this week only.', reason: 'Reads better' }
    const calls = agent({ ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'ready', candidate: BRIAN_TAKE }, suggestion] })
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')

    await user.click(await screen.findByRole('button', { name: 'Add to plan' }))

    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/items/i2'))?.body).toEqual({ include: true }))
  })

  it('remembers Just do it, and a drafted plan runs at once', async () => {
    const drafted = { ...PLAN, mode: 'draft', status: 'running', job_id: 'j1', items: [{ ...PLAN_ITEM, status: 'working', progress: 'Synthesizing the new line' }] }
    const calls = agent(drafted, PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByRole('button', { name: 'Just do it' }))
    expect(calls.find((c) => c.url.endsWith('/settings'))?.body).toEqual({ autonomy: 'draft' })
    expect(screen.getByRole('button', { name: 'Just do it' })).toHaveAttribute('aria-pressed', 'true')

    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'make it 30% off{Enter}')

    await waitFor(() => expect(screen.getByText("Take · Brian's voice")).toBeInTheDocument())
    expect(calls.some((c) => c.url.endsWith('/run'))).toBe(false)   // no Go ahead needed
  })

  it('shows what Voltage noticed, asks one thing, and plans with the answer', async () => {
    const calls = agent(PLAN_CLARIFYING)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')

    const thinking = await screen.findByTestId('thinking')
    expect(thinking).toHaveTextContent('The offer is said once, at 0:00.')
    const ask = screen.getByTestId('clarify')
    expect(ask).toHaveTextContent('Who speaks for the brand?')
    expect(ask).toHaveTextContent('My guess is The Shopkeeper.')
    expect(screen.queryByRole('button', { name: 'Go ahead' })).not.toBeInTheDocument()   // the plan waits behind the question

    await user.click(within(ask).getByRole('button', { name: 'The Customer' }))

    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/clarify'))?.body).toEqual({ answer: 'The Customer' }))
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go ahead' })).toBeEnabled()
  })

  it('saying "go" takes the guess', async () => {
    const calls = agent(PLAN_CLARIFYING)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await screen.findByTestId('clarify')

    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'go{Enter}')

    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/clarify'))?.body).toEqual({}))
  })

  it('hears the seam: plays the edited video across the change', async () => {
    const calls = agent()
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Go ahead' }))
    await user.click(await screen.findByRole('button', { name: 'Review 1 ready change' }))

    await user.click(screen.getByRole('button', { name: /hear the seam/i }))

    // No render yet, so the original at that line, from a moment before it.
    const video = container.querySelector('video') as HTMLVideoElement
    expect(video.currentTime).toBe(0)   // 0.4 - 1.5, clamped
    expect(calls.length).toBeGreaterThan(0)
  })

  it('offers tighter wordings while you edit a line, and Voltage stands by', async () => {
    const asks: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/lines/reword')) {
        const body = JSON.parse(String(init?.body))
        asks.push(body)
        return ok({ text: body.instruction ? 'Get 30% off, today.' : 'Get 30% off today.', selection: { start: 0, end: 2.3 } })
      }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    expect(screen.getByText(/standing by/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /ask voltage for wording/i }))

    const offers = await screen.findByTestId('offers')
    expect(asks).toHaveLength(2)
    await user.click(within(offers).getByRole('button', { name: 'Get 30% off, today.' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Get 30% off, today.')
  })

  it('changes the plan in words, in place, from the box (UX-2)', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await screen.findByRole('checkbox', { name: 'Include the change at 0:00' })

    const box = screen.getByRole('textbox', { name: /describe a change/i })
    expect(box).toHaveAttribute('placeholder', expect.stringContaining('Change the plan in your words'))
    await user.type(box, 'not that one{Enter}')

    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/plans/plan1/revise'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/revise'))!.body).toEqual({ instruction: 'not that one' })
    // The same plan, changed: no second plan was made.
    expect(calls.filter((c) => c.url.endsWith('/plans'))).toHaveLength(1)
    expect(await screen.findByText('Left the change out.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Include the change at 0:00' })).not.toBeChecked()
  })

  it('sets a delivery on a planned change and can stop a running plan (UX-2)', async () => {
    const calls = agent(PLAN, { ...PLAN, status: 'running', items: [{ ...PLAN_ITEM, status: 'working' }] })
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    await screen.findByRole('checkbox', { name: 'Include the change at 0:00' })
    await user.click(within(screen.getByRole('group', { name: 'Delivery at 0:00' })).getByRole('button', { name: 'calmer' }))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/items/i1') && (c.body as { delivery?: string }).delivery === 'calmer')).toBe(true))

    await user.click(screen.getByRole('button', { name: 'Go ahead' }))
    await user.click(await screen.findByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/plans/plan1/stop'))).toBe(true))
    expect(await screen.findByText('Stopping after this line…')).toBeInTheDocument()
  })

  it('reopens a project with its plan', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects/p1')) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', edits: [], messages: [{ role: 'user', text: 'make it 30% off' }],
          settings: { long_lines: 'pause', autonomy: 'ask' }, plan: PLAN_DONE })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    render(<App />)
    expect(await screen.findByText("Take · Brian's voice")).toBeInTheDocument()
    expect(screen.queryByText('What should this video say?')).not.toBeInTheDocument()
  })
})

describe('App fit notes (Phase 14)', () => {
  it('shows how the take was fitted under the line', async () => {
    const fitted = { ...CANDIDATE, fit_notes: ['nearest of 3 takes', 'trimmed 120 ms of pauses'] }
    vi.stubGlobal('fetch', routeFetch(200, { ...JOB_DONE, result: fitted }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    const take = await screen.findByTestId('take')
    expect(take).toHaveTextContent('Trimmed 120 ms of pauses')

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Change the words' }))
    expect(screen.getByTestId('readout')).toHaveTextContent(/nearest of 3 takes.*trimmed 120 ms of pauses.*voice at natural speed/)
  })
})

describe('App panel order', () => {
  it('puts the receipt above the plan and the action last', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects/p1')) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', edits: [], messages: [{ role: 'user', text: 'make it 30% off' }],
          settings: { long_lines: 'pause', autonomy: 'ask' }, plan: PLAN_DONE })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    render(<App />)
    await screen.findByTestId('next-action')
    const panel = screen.getByTestId('activity').parentElement as HTMLElement
    const ids = Array.from(panel.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid'))
    expect(ids.indexOf('activity')).toBeLessThan(ids.indexOf('plan'))
    expect(ids[ids.length - 1]).toBe('next-action')
  })

  it('tells you when a clip has no speech, instead of inviting a goal', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/projects') && init?.method === 'POST') return ok({ ...PROJECT, transcript: [], statements: [] })
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    expect(await screen.findByText(/no speech in this clip/i)).toBeInTheDocument()
    expect(screen.queryByText('What should this video say?')).not.toBeInTheDocument()
  })
})

describe('App keyboard (UX-4)', () => {
  it('puts the cursor in the box on "/" from the transcript, and leaves a typed "/" alone', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    act(() => (document.getElementById('line-0') as HTMLElement).focus())
    await user.keyboard('/')
    const box = screen.getByRole('textbox', { name: /describe a change/i })
    expect(box).toHaveFocus()
    expect(box).toHaveValue('')
    await user.keyboard('a/b')
    expect(box).toHaveValue('a/b')
  })
})

describe('App: the line is the unit (UX-1)', () => {
  it('keeps a take from the row, and the line shows it with Undo', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    const take = await screen.findByTestId('take')
    expect(screen.getByTestId('line-action')).toHaveTextContent('One line is ready to hear.')

    await user.click(within(take).getByRole('button', { name: 'Keep' }))

    await waitFor(() => expect(screen.getByText('Kept')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits'))).toBe(true)
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/export'))).toBe(true)
    expect(screen.queryByTestId('take')).not.toBeInTheDocument()
  })

  it('asks for another take and shows both as a choice', async () => {
    let n = 0
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/jobs/')) { n += 1; return ok({ ...JOB_DONE, result: { ...CANDIDATE, candidate_id: `c${n}` } }) }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Another take' }))

    await waitFor(() => expect(screen.getAllByTestId('take')).toHaveLength(2))
    expect(screen.getByRole('button', { name: 'Keep take 2' })).toBeInTheDocument()
  })

  it('removes a line: struck through, room tone in its place, undo at hand', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.getByText('Removed')).toBeInTheDocument())
    expect(screen.getByText('Get 20% off today only.').tagName).toBe('DEL')
    expect(f.mock.calls.some(([url, init]) => String(url).endsWith('/lines/remove') && init?.method === 'POST')).toBe(true)
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })

  it('adds a line after a line, over the picture by default', async () => {
    const bodies: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/preview')) bodies.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Add a line after' }))
    await user.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Hurry, it ends Sunday.{Enter}')

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ text: 'Hurry, it ends Sunday.', mix: 'over', start: 0, end: 2.3 })
    await screen.findByTestId('take')
  })

  it('plays a take in place: the video runs from the line with the take over it', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachEditor(user)
    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    const take = await screen.findByTestId('take')

    await user.click(within(take).getByRole('button', { name: /play take 1 in the video/i }))

    const video = container.querySelector('video') as HTMLVideoElement
    expect(video.currentTime).toBe(0.4)
    expect(video.muted).toBe(true)   // a replacement: the original's words are off
    expect(within(take).getByRole('button', { name: /play take 1 in the video/i })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('App: shifting original speech (UX-1c)', () => {
  it('shifts a line to a typed time: room tone where it was, the words over the picture there, undo for both', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Shift' }))
    const box = screen.getByRole('textbox', { name: 'Starts at' })
    await user.clear(box)
    await user.type(box, '0:01.00')
    await user.click(screen.getByRole('button', { name: 'Put it here' }))

    await waitFor(() => expect(f.mock.calls.some(([url, init]) => String(url).endsWith('/lines/shift')
      && JSON.parse(String(init?.body)).to === 1)).toBe(true))
    // Where it was, and its own row where it now plays.
    expect(await screen.findByText('Moved away')).toBeInTheDocument()
    expect(screen.getByText(/Moved to 0:01\.00/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: 'Moved line at 0:01' })).toHaveTextContent('Get 20% off today only.')
    expect(screen.getByText('Moved')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Undo' })[0])
    await waitFor(() => expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/e8/revert'))).toBe(true))
    await waitFor(() => expect(screen.queryByText('Moved')).not.toBeInTheDocument())
    expect(screen.queryByText('Moved away')).not.toBeInTheDocument()
  })
})

describe('App: moving audio on the timeline (UX-1b)', () => {
  it('moves a take to a typed time and shows the moved take under the line', async () => {
    const calls: { url: string; body: unknown }[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/candidates/c1/move')) {
        calls.push({ url, body: JSON.parse(String(init?.body)) })
        return ok({ ...CANDIDATE, candidate_id: 'c2', plan: { ...CANDIDATE.plan, selection: { start: 1.5, end: 2.0 }, fit: 'start' }, fit_notes: ['moved to 0:01'] })
      }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await user.click(screen.getByText('Get 20% off today only.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    const place = within(await screen.findByTestId('take')).getByTestId('place')

    await user.click(within(place).getByRole('button', { name: 'Move' }))
    expect(screen.getByRole('slider', { name: 'Where the take starts' })).toBeInTheDocument()
    const field = within(screen.getByTestId('place')).getByRole('textbox', { name: 'Starts at' })
    await user.clear(field)
    await user.type(field, '1.5{Enter}')

    await waitFor(() => expect(calls).toEqual([{ url: '/api/projects/p1/candidates/c1/move', body: { start: 1.5 } }]))
    await waitFor(() => expect(screen.getByTestId('place')).toHaveTextContent('Starts at 0:01.50'))
    expect(screen.queryByRole('slider', { name: 'Where the take starts' })).not.toBeInTheDocument()
  })

  it('moves a kept line in one step and re-renders', async () => {
    const calls: string[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/e1/move')) {
        calls.push(String(init?.body))
        return ok({ edit_id: 'e2', reverted: 'e1', candidate: { ...CANDIDATE, candidate_id: 'c3', plan: { ...CANDIDATE.plan, selection: { start: 1.3, end: 1.8 } } } })
      }
      if (url.endsWith('/projects/p1')) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', messages: [{ role: 'user', text: 'x' }], settings: { long_lines: 'pause', autonomy: 'ask' },
          edits: [{ edit_id: 'e1', candidate_id: 'c1', new_text: '30% off', selection: { start: 0.4, end: 0.9 }, mix: 'replace', overridden: false, reverted: false }] })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    const user = userEvent.setup()
    render(<App />)
    const place = await screen.findByTestId('place')
    await user.click(within(place).getByRole('button', { name: 'Move' }))
    await user.click(within(screen.getByTestId('place')).getByRole('button', { name: 'Put it here' }))

    await waitFor(() => expect(calls).toEqual(['{"start":0.4}']))
    await waitFor(() => expect(screen.getByTestId('place')).toHaveTextContent('Starts at 0:01.30'))
  })

  it('adds a line at a chosen time: layered there at its natural length', async () => {
    const bodies: Record<string, unknown>[] = []
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/edits/preview')) bodies.push(JSON.parse(String(init?.body)))
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await user.click(screen.getByRole('button', { name: /add a line here/i }))
    await user.type(screen.getByRole('textbox', { name: 'Starts at' }), '1.1')
    await user.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Welcome.{Enter}')
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ text: 'Welcome.', mix: 'layer', fit: 'start', start: 1.1 })
  })
})


describe('App sign-in (Phase 9c)', () => {
  const ME = { mode: 'google', user: { sub: '42', email: 'ash@example.com', name: 'Ash', picture: null } }

  it('shows the door when sign-in is on and nobody is in', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/me')) return ok({ mode: 'google', user: null })
      return base(url, init)
    }))
    render(<App />)
    const door = await screen.findByRole('link', { name: /sign in with google/i })
    expect(door).toHaveAttribute('href', '/api/auth/login')
    expect(screen.queryByRole('button', { name: /sample ad/i })).not.toBeInTheDocument()
  })

  it('names who is in, sends writes as Voltage, and signs out', async () => {
    const base = routeFetch()
    const calls: { url: string; init?: RequestInit }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (url.endsWith('/auth/me')) return ok(ME)
      if (url.endsWith('/auth/logout')) return ok({ signed_out: true })
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByTestId('who')).toHaveTextContent('Ash')
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    await screen.findByText('What should this video say?')
    const upload = calls.find((c) => c.url.endsWith('/projects') && c.init?.method === 'POST')
    expect((upload!.init!.headers as Record<string, string>)['X-Requested-With']).toBe('voltage')

    await user.click(screen.getByRole('button', { name: /edit a line yourself/i }))
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(calls.some((c) => c.url.endsWith('/auth/logout') && c.init?.method === 'POST')).toBe(true)
    expect(await screen.findByRole('link', { name: /sign in with google/i })).toBeInTheDocument()
  })

  it('goes back to the door when the session ends', async () => {
    const base = routeFetch()
    const gone = { ok: false, status: 401, json: async () => ({ detail: 'Sign in to continue.' }), text: async () => JSON.stringify({ detail: 'Sign in to continue.' }) } as Response
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/me')) return ok(ME)
      if (url.endsWith('/projects') && init?.method === 'POST') return gone
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    expect(await screen.findByRole('link', { name: /sign in with google/i })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Your session ended')
  })
})
