import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const SOURCE_MEDIA = {
  kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4',
}

const PROJECT = {
  statements: [{ text: 'Get 20% off today only.', start: 0.0, end: 2.3 }],
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
  new_text: 'Get 30% off today only.', speaker: null, mix: 'replace', reason: 'The offer',
  kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null,
  question: null, error: null, note: null,
}
const PLAN = {
  type: 'plan', plan_id: 'plan1', goal: 'make it 30% off', summary: 'I read 1 line. One change does it.',
  mode: 'ask', status: 'proposed', created_at: '2026-10-02T10:00:00Z',
  estimate: { items: 1, voice_characters: 23, usd: 0.0069, seconds: 12 },
  log: [{ at: '2026-10-02T10:00:00Z', text: 'Read your goal and all 1 lines', detail: 'Claude' }],
  items: [PLAN_ITEM],
}
const BRIAN_TAKE = { ...CANDIDATE, plan: { ...CANDIDATE.plan, voice_profile_id: 'nPczCjzI2devNBz1zQrb' } }
const PLAN_DONE = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'ready', candidate: BRIAN_TAKE }] }
const PLAN_APPROVED = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'approved', candidate: BRIAN_TAKE, edit_id: 'e1' }],
  log: [...PLAN.log, { at: '2026-10-02T10:01:00Z', text: 'Rendered the edited video', detail: '$0.02 in total' }] }

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
    if (url.endsWith('/settings')) {
      return ok({ settings: { long_lines: JSON.parse(String(_init?.body)).long_lines } })
    }
    if (url.endsWith('/lines/reword')) {
      return ok({ text: 'Get 30% off today.', selection: { start: 0, end: 2.3 } })
    }
    if (url.endsWith('/plans')) return ok(PLAN)
    if (/\/plans\/plan1$/.test(url)) return ok(PLAN)
    if (url.includes('/plans/plan1/items/') && _init?.method === 'PUT') return ok(PLAN)
    if (url.endsWith('/plans/plan1/run') || url.endsWith('/answer') || url.endsWith('/redo')) return ok({ ...JOB_ACCEPTED, kind: 'plan' })
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

/** consent -> load -> editor, leaving the app on the editor screen. */
async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: /continue/i }))
  await user.click(screen.getByRole('button', { name: /sample ad/i }))
  await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())
}

beforeEach(() => {
  vi.restoreAllMocks()
  window.location.hash = ''   // opening a project writes its id here
})

describe('App full journey', () => {
  it('runs consent → load → select → preview → approve → export', async () => {
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
    await user.type(screen.getByRole('textbox', { name: /describe a change/i }), 'change "20% off" to "30% off"')
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
    await user.click(screen.getByRole('button', { name: /preview change/i }))

    await waitFor(() => expect(screen.getByText(/continuity checked/i)).toBeInTheDocument())
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
    expect(await screen.findByText('Get 20% off today only.')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
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

    await userEvent.setup().click(screen.getByRole('button', { name: 'Revert' }))

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
    expect(screen.getByText('Ready')).toBeInTheDocument()   // the line's status
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

    await waitFor(() => expect(screen.getByText('Working')).toBeInTheDocument())
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
    await reachEditor(user)

    // Screen A: the goal.
    expect(screen.getByText('What should your video say?')).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /your goal/i }), 'make it 30% off')
    await user.click(screen.getByRole('button', { name: /plan the edits/i }))

    // Screen D: the plan waits.
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
    expect(calls[0]).toMatchObject({ body: { goal: 'make it 30% off' } })
    expect(screen.getByRole('checkbox', { name: 'Include the change at 0:00' })).toBeChecked()
    expect(screen.getByText(/about 23 voice characters/i)).toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()   // on the transcript line
    expect(screen.queryByText(/approve/i)).not.toBeInTheDocument()

    // Run it.
    await user.click(screen.getByRole('button', { name: 'Run 1 change' }))
    await waitFor(() => expect(screen.getByText("Take, Brian's voice")).toBeInTheDocument())
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/run'))).toBe(true)
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByTestId('activity')).toHaveTextContent('Read your goal and all 1 lines')

    // Screen C: review and ship.
    await user.click(screen.getByRole('button', { name: 'Review 1 ready change' }))
    expect(screen.getByText('1 change is ready')).toBeInTheDocument()
    expect(screen.getByTestId('review-row')).toHaveTextContent('Before')
    await user.click(screen.getByRole('button', { name: 'Approve all 1 and export' }))

    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src'))
      .toBe(`/api/projects/p1/artifacts/${'r'.repeat(64)}`))
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/approve'))).toBe(true)
    expect(screen.getAllByText('Approved').length).toBeGreaterThan(0)
    expect(screen.getByTestId('activity')).toHaveTextContent('Rendered the edited video')
  })

  it('unticks and rewords a planned change before running', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await user.type(screen.getByRole('textbox', { name: /your goal/i }), 'make it 30% off{Enter}')
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
    await reachEditor(user)
    await user.type(screen.getByRole('textbox', { name: /your goal/i }), 'make it 30% off{Enter}')

    expect(await screen.findByText('Needs you')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /use a shorter line/i }))

    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/items/i1/answer'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/answer'))?.body).toEqual({ text: '30% off today.' })
    await waitFor(() => expect(screen.getByText('Ready')).toBeInTheDocument())
  })

  it('adds a suggestion to the plan', async () => {
    const suggestion = { ...PLAN_ITEM, item_id: 'i2', kind: 'suggestion', enabled: false, status: 'suggested',
      new_text: 'Get 30% off this week only.', reason: 'Reads better' }
    const calls = agent({ ...PLAN, items: [PLAN_ITEM, suggestion] })
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)
    await user.type(screen.getByRole('textbox', { name: /your goal/i }), 'make it 30% off{Enter}')

    await user.click(await screen.findByRole('button', { name: 'Add to plan' }))

    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/items/i2'))?.body).toEqual({ include: true }))
  })

  it('remembers Draft everything, and a drafted plan runs at once', async () => {
    const drafted = { ...PLAN, mode: 'draft', status: 'running', job_id: 'j1', items: [{ ...PLAN_ITEM, status: 'working' }] }
    const calls = agent(drafted, PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByRole('button', { name: 'Draft everything' }))
    expect(calls.find((c) => c.url.endsWith('/settings'))?.body).toEqual({ autonomy: 'draft' })
    expect(screen.getByRole('button', { name: 'Draft everything' })).toHaveAttribute('aria-pressed', 'true')

    await user.type(screen.getByRole('textbox', { name: /your goal/i }), 'make it 30% off{Enter}')

    await waitFor(() => expect(screen.getByText("Take, Brian's voice")).toBeInTheDocument())
    expect(calls.some((c) => c.url.endsWith('/run'))).toBe(false)   // no Run needed
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
    expect(await screen.findByText("Take, Brian's voice")).toBeInTheDocument()
    expect(screen.queryByText('What should your video say?')).not.toBeInTheDocument()
  })
})
