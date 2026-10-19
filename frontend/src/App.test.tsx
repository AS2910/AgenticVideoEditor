import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const SOURCE_MEDIA = {
  kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4',
}

const PROJECT = {
  statements: [{ text: 'Get 20% off today only.', start: 0.0, end: 2.3 }],
  consent_granted_at: '2026-09-26T08:00:00.000Z',
  video_id: 'p1',
  project_id: null,
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
const PLAN_APPROVED = { ...PLAN, status: 'done', takes_voiced: 3, items: [{ ...PLAN_ITEM, status: 'approved', candidate: BRIAN_TAKE, edit_id: 'e1' }],
  log: [...PLAN.log, { at: '2026-10-02T10:01:00Z', text: 'Rendered the edited video', detail: '$0.02 in total' }] }

/** A removal proposed by hand (20e): a ready item whose take is the room's own sound. */
const PLAN_REMOVAL = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, item_id: 'i7', mix: 'remove', new_text: '', status: 'ready',
  candidate: { ...CANDIDATE, candidate_id: 'c7', plan: { ...CANDIDATE.plan, selection: { start: 0, end: 2.3 }, new_text: '', mix: 'remove' } } }] }

const READING = { opening: 'One person, one line. The offer is said once, at 0:00.', roles: [] }

const JOB_ACCEPTED = {
  job_id: 'j1', kind: 'turn', project_id: 'p1',
  status: 'queued', progress: 0, step: 'Queued',
  attempts: 0, result: null, error: null,
}

/** A turn that came back with nothing new: no plan, no question. */
const JOB_TURN = {
  ...JOB_ACCEPTED, status: 'succeeded', progress: 1, step: 'Done',
  result: { type: 'turn', plan: null, reply: '', question: null },
}

const TEXTBOX = { name: /describe a change/i }
const saidTo = (calls: { url: string; body: unknown }[]) =>
  calls.filter((c) => c.url.endsWith('/turns')).map((c) => (c.body as { text: string }).text)

/** Routes by URL. `job` overrides the polled job so a test can exercise the failure path. */
function routeFetch(job: unknown = JOB_TURN) {
  return vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.includes('/jobs/')) return ok(job)
    if (url.endsWith('/revert')) return ok({ edit_id: 'e1', reverted: true })
    if (url.endsWith('/lines/remove')) return ok({ item_id: 'i7', candidate_id: 'c7', selection: { start: 0, end: 2.3 }, mix: 'remove', plan: PLAN_REMOVAL })
    if (url.endsWith('/lines/shift')) {
      return ok({ edit_id: 'e9', removed_edit_id: 'e8', candidate: CANDIDATE, from: { start: 0, end: 2.3 }, selection: { start: 1.0, end: 2.3 }, mix: 'layer' })
    }
    if (url.endsWith('/settings')) return ok({ settings: JSON.parse(String(_init?.body)) })
    if (url.endsWith('/auth/me')) return ok({ mode: 'off', user: null })
    if (url.endsWith('/reading')) return ok(READING)
    if (url.endsWith('/turns')) return ok(JOB_ACCEPTED)
    if (url.includes('/messages?after=')) return ok([])
    if (/\/plans\/plan1$/.test(url)) return ok(PLAN)
    if (url.endsWith('/plans/plan1/approve')) {
      return ok({ approved: [{ item_id: 'i1', edit_id: 'e1', overridden: false }], skipped: [],
        export: { segments: SEGMENTS, render: RENDER }, plan: PLAN_APPROVED })
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
    if (url.endsWith('/videos/p1') && !_init?.method) return ok({ ...PROJECT, created_at: '2026-09-26T08:00:00Z', edits: [], messages: [] })
    if (url.endsWith('/videos') && _init?.method === 'POST') return ok(PROJECT)
    if (/\/videos(\?|$)/.test(url) && !_init?.method) return ok({ videos: [] })
    if (url.endsWith('/projects') && !_init?.method) return ok({ projects: [] })
    // The sample clip is fetched from /public, then uploaded like any file.
    if (url.endsWith('/sample-ad.mp4')) {
      return { ok: true, status: 200, blob: async () => new Blob(['mp4-bytes']) } as Response
    }
    throw new Error(`unexpected url ${url}`)
  })
}

/** Voltage as an agent (Phase 13, 20c): every POST /turns answers with the
 *  plan `onTurn` gives for the words said, says its summary or question in
 *  the thread, and the job's result is that plan. Ship goes through /approve. */
function agent(initial: unknown = PLAN, onTurn: (text: string) => unknown = () => initial) {
  const calls: { url: string; body: unknown }[] = []
  let current = initial
  const said: { role: string; text: string; kind: string; seq: number }[] = []
  const base = routeFetch()
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (url.endsWith('/turns') && init?.method === 'POST') {
      calls.push({ url, body }); current = onTurn((body as { text: string }).text)
      const p = current as { summary: string; question?: { text: string } | null }
      said.push({ role: 'assistant', text: p.question ? p.question.text : p.summary, kind: 'say', seq: said.length + 2 })
      return ok(JOB_ACCEPTED)
    }
    if (url.includes('/messages?after=')) { const after = Number(url.split('after=')[1]); return ok(said.filter((m) => m.seq > after)) }
    if (url.includes('/jobs/')) {
      const p = current as { question?: unknown }
      return ok({ ...JOB_TURN, result: { type: 'turn', plan: current, reply: '', question: p.question ?? null } })
    }
    if (/\/plans\/plan1$/.test(url)) return ok(current)
    // The project as the server has it: the plan's approved items are its live edits (20g: the panel syncs edits after a turn).
    if (url.endsWith('/videos/p1') && !init?.method) {
      const p = current as { items?: { status: string; edit_id: string | null; selection: { start: number; end: number }; new_text: string; mix: string; candidate: { candidate_id: string } | null }[] } | null
      const edits = (p?.items ?? []).filter((i) => i.status === 'approved' && i.edit_id).map((i) => ({
        edit_id: i.edit_id, candidate_id: i.candidate?.candidate_id ?? 'c1', selection: i.selection, new_text: i.new_text, mix: i.mix, old_text: '', reverted: false,
      }))
      return ok({ ...PROJECT, created_at: '2026-09-26T08:00:00Z', edits, messages: [] })
    }
    if (url.endsWith('/approve')) { calls.push({ url, body }); current = PLAN_APPROVED }
    if (url.endsWith('/settings')) calls.push({ url, body })
    return base(url, init)
  })
  vi.stubGlobal('fetch', f)
  return calls
}

/** load -> the workspace, where Voltage has read the clip (its first message, UX-7c). */
async function reachGoal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /sample ad/i }))
  await screen.findByTestId('first-read')
  await screen.findByText('Get 20% off today only.')
}

/** load -> the workspace, with the word timeline open. */
async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
  await reachGoal(user)
  // The word timeline sits behind Tracks › Precise; a few of these tests select a word on it.
  await user.click(screen.getByRole('button', { name: 'Tracks' }))
  await user.click(screen.getByRole('button', { name: 'Precise' }))
  await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())
}

/** Volt: Just do it lives in the What Voltage may do sheet, behind the header's autonomy word. */
async function justDoIt(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /check with me/i }))
  const sheet = await screen.findByRole('dialog', { name: 'What Voltage may do' })
  await user.click(within(sheet).getByRole('button', { name: 'Just do it' }))
  await user.keyboard('{Escape}')
}
const verbNames = (group: HTMLElement) => within(group).getAllByRole('button').map((b) => b.textContent?.replace(/[␣K]$/, ''))

/** Open the first line's editor and ask for new words: one turn to Voltage. */
async function hearNewWords(user: ReturnType<typeof userEvent.setup>, words = 'Get 30% off today only.') {
  await user.click(screen.getByText('Get 20% off today only.'))
  const box = screen.getByRole('textbox', { name: /new wording/i })
  await user.clear(box)
  await user.type(box, `${words}{Enter}`)
}

beforeEach(() => {
  vi.restoreAllMocks()
  window.location.hash = ''   // opening a project writes its id here
})

describe('App full journey', () => {
  it('runs load → a goal → Voltage voices the line → the ship card → Ship → export', async () => {
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)

    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'change "20% off" to "30% off"{Enter}')

    // Everything goes through one door.
    expect(calls[0]).toMatchObject({ url: '/api/videos/p1/turns', body: { text: 'change "20% off" to "30% off"' } })
    await waitFor(() => expect(screen.getAllByTestId('take').some((t) => t.textContent?.includes("Brian's voice"))).toBe(true))
    await waitFor(() => expect(screen.getByTestId('spend')).toHaveTextContent('$0.01'))
    // 20e: the proposal is a row in the one transcript, with its verbs; nothing to ship in the panel.
    expect(screen.queryByRole('group', { name: 'Ready to ship' })).toBeNull()
    expect(screen.getByText('Proposed')).toBeInTheDocument()
    await user.click(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Add it' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/plans/plan1/approve'))?.body).toEqual({ items: ['i1'] }))
    expect(screen.queryByTestId('ship-sheet')).toBeNull()

    // Volt: the line is in the video; the file is on the export page.
    await waitFor(() => expect(screen.getByText('✓ In the video')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Export' })).toHaveAttribute('href', '#v/p1/export')
  })

  it("says in the thread when a turn fails on Voltage's side, and stops waiting", async () => {
    vi.stubGlobal('fetch', routeFetch({ ...JOB_ACCEPTED, status: 'failed', progress: 0.55, step: 'Failed', attempts: 3, error: 'The voice service was busy. Nothing was charged.' }))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await user.type(screen.getByRole('textbox', TEXTBOX), 'change "20% off" to "30% off"{Enter}')

    await waitFor(() => expect(screen.getByText('The voice service was busy. Nothing was charged.')).toBeInTheDocument())
    expect(screen.queryByTestId('turn-working')).not.toBeInTheDocument()
  })

  it('uploads without consent; when a paid step needs it, the sheet asks in a sentence and the same turn goes again (UX-3)', async () => {
    const refusal = 'Confirm you have the right to edit and clone this speaker before generating.'
    const calls = agent(PLAN_DONE)
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    const granted: string[] = []
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos') && init?.method === 'POST') return ok({ ...PROJECT, consent_granted_at: null })
      if (url.endsWith('/consent')) { granted.push(url); return ok({ video_id: 'p1', consent_granted_at: '2026-10-04T10:00:00.000Z' }) }
      if (url.endsWith('/turns') && granted.length === 0) {
        return { ok: false, status: 403, json: async () => ({ detail: refusal }), text: async () => JSON.stringify({ detail: refusal }) } as Response
      }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    const upload = f.mock.calls.find(([url, init]) => String(url).endsWith('/videos') && init?.method === 'POST')
    expect((upload![1]!.body as FormData).get('consent')).toBe('false')

    await user.type(screen.getByRole('textbox', TEXTBOX), 'change "20% off" to "30% off"{Enter}')

    // The server refused the turn for want of consent: the question, not the refusal, is what you see.
    const sheet = await screen.findByRole('dialog')
    expect(sheet).toHaveTextContent("I'll be creating speech in this person's voice")
    expect(screen.queryByText(refusal)).not.toBeInTheDocument()
    expect(calls).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /not yet/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(granted).toHaveLength(0)

    await user.type(screen.getByRole('textbox', TEXTBOX), 'change "20% off" to "30% off"{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Yes, I have it' }))
    await waitFor(() => expect(granted).toHaveLength(1))
    // Once, with the words as said; then the plan comes back as on any turn.
    await waitFor(() => expect(saidTo(calls)).toEqual(['change "20% off" to "30% off"']))
    await waitFor(() => expect(screen.getAllByTestId('take').some((t) => t.textContent?.includes("Brian's voice"))).toBe(true))
  })

  it('opens on the load screen; no gate before anything is seen', async () => {
    vi.stubGlobal('fetch', routeFetch())
    render(<App />)
    expect(await screen.findByRole('button', { name: /sample ad/i })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('sends words typed with a selection as a turn that names the time', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()   // one button, one meaning
    await user.type(screen.getByRole('textbox', TEXTBOX), 'say 30% off{Enter}')

    await waitFor(() => expect(saidTo(calls)).toEqual(['At 0:00: say 30% off']))
  })
})

describe('App playback after shipping', () => {
  it('renders the shipped change and plays it, with the original a click away', async () => {
    agent(PLAN_DONE)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)

    await user.type(screen.getByRole('textbox', TEXTBOX), 'change "20% off" to "30% off"{Enter}')
    // 20e: with a proposal waiting, the player offers "With proposals" beside Original.
    expect(within(await screen.findByRole('group', { name: 'Play' })).getAllByRole('button').map((b) => b.textContent)).toEqual(['With proposals', 'As shot'])
    await user.click(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Add it' }))

    const video = () => container.querySelector('video') as HTMLVideoElement
    const renderUrl = `/api/videos/p1/artifacts/${'r'.repeat(64)}`
    await waitFor(() => expect(video().getAttribute('src')).toBe(renderUrl))
    expect(screen.getByRole('button', { name: 'Edited' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: 'With proposals' })).toBeNull()   // nothing is proposed any more

    await user.click(screen.getByRole('button', { name: 'As shot' }))
    expect(video().getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'s'.repeat(64)}`)
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
      if (/\/videos(\?|$)/.test(url) && init?.method !== 'POST') {
        return ok({ videos: [{ video_id: 'p1', project_id: null, filename: 'sample-ad.mp4', duration: 2.3,
          created_at: '2026-09-26T08:00:00Z', edits: 1 }] })
      }
      if (url.endsWith('/videos/p1') && init?.method === 'DELETE') {
        return { ok: true, status: 204, text: async () => '' } as Response
      }
      if (url.endsWith('/videos/p1')) return ok(DETAIL)
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
      .getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'r'.repeat(64)}`))
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/export'))).toBe(true)
  })

  it('deletes a project after asking once more', async () => {
    const f = withProjects()
    const user = userEvent.setup()
    render(<App />)
    await toLoadScreen(user)

    await user.click(await screen.findByRole('button', { name: 'More for sample-ad.mp4' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete…' }))
    await user.click(screen.getByRole('button', { name: /delete for good/i }))

    // The delete waits five seconds behind "Deleted · Undo" before it goes through (UX-6).
    await waitFor(() => expect(f.mock.calls.some(
      ([url, init]) => String(url).endsWith('/videos/p1') && init?.method === 'DELETE')).toBe(true), { timeout: 7000 })
  }, 12000)

  it('goes back to the project list from the editor', async () => {
    withProjects()
    const user = userEvent.setup()
    render(<App />)
    await toLoadScreen(user)
    await user.click(await screen.findByText('sample-ad.mp4'))
    await screen.findByText('Earlier reply.')

    await user.click(screen.getByRole('link', { name: /all projects/i }))

    expect(await screen.findByRole('button', { name: /sample ad/i })).toBeInTheDocument()
  })
})

describe('App editing at the line (Phase 10, 20c)', () => {
  it('edits a line in place: Voice it says the change to Voltage, in the chosen voice and delivery', async () => {
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    await screen.findByRole('option', { name: 'Brian (male)' })   // the voices have reached the editor's picker
    await user.selectOptions(screen.getByRole('combobox', { name: 'Voice' }), 'nPczCjzI2devNBz1zQrb')
    await user.click(screen.getByRole('button', { name: 'Warmer' }))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.')
    await user.click(screen.getByRole('button', { name: 'Voice it' }))

    expect(saidTo(calls)).toEqual(["Replace the line at 0:00 (“Get 20% off today only.”) with “Get 30% off today only.”, said warmer, in Brian's voice"])
    // The take comes back under the line, not in the panel.
    expect(await screen.findByTestId('take')).toHaveTextContent("Brian's voice ·")
  })

  it('leaves the voice and the delivery out of the sentence when neither was chosen', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await hearNewWords(user)
    expect(saidTo(calls)).toEqual(['Replace the line at 0:00 (“Get 20% off today only.”) with “Get 30% off today only.”'])
  })
})

describe('App goal stage shows the clip (UX-2)', () => {
  it('reads the clip once, names the speaker by role, and confirms the guess', async () => {
    const base = routeFetch()
    const reads: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos') && init?.method === 'POST') {
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
    expect(screen.getByTestId('cast')).toHaveTextContent('the Presenter')
    expect(screen.getByTestId('cast')).toHaveTextContent(/my guess/i)
    await user.click(screen.getByRole('button', { name: /looks right/i }))
    await waitFor(() => expect(reads).toContain('PUT Presenter'))
    // Confirmed: no longer a guess, and the line shows the name.
    await waitFor(() => expect(screen.getByTestId('cast')).not.toHaveTextContent(/my guess/i))
    expect(screen.getByTestId('cast')).toHaveTextContent('Presenter')
    expect(reads.filter((r) => r.endsWith('/reading'))).toHaveLength(1)
  })
})

describe('App speakers (Phase 11)', () => {
  it('detects speakers, then names them (Volt: in Who\'s speaking)', async () => {
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

    await user.click(screen.getByRole('button', { name: /find who speaks/i }))
    const cast = await screen.findByTestId('cast')
    await user.click(within(cast).getByRole('button', { name: 'Rename' }))
    const name = await screen.findByRole('textbox', { name: 'Name for speaker A' })
    await user.clear(name)
    await user.type(name, 'Presenter{Enter}')

    await waitFor(() => expect(puts.map((p) => p.body)).toEqual([{ name: 'Presenter' }]))
    expect(screen.getByTestId('cast')).toHaveTextContent('Presenter')
  })
})

describe('App reopening from the URL (redesign)', () => {
  it('opens the project named in the URL, skipping the upload screens', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1')) {
        return ok({ ...PROJECT, created_at: '2026-09-26T08:00:00Z', edits: [], messages: [] })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    render(<App />)
    // A fresh project opens in the workspace, read by Voltage; every line is there to click.
    expect(await screen.findByTestId('first-read')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(await screen.findByText('Get 20% off today only.')).toBeInTheDocument()
  })
})

describe('App undo (Phase 12)', () => {
  const DETAIL = {
    ...PROJECT,
    created_at: '2026-09-26T08:00:00Z',
    settings: { autonomy: 'ask' },
    edits: [
      { edit_id: 'e1', candidate_id: 'c1', new_text: '30% off',
        selection: { start: 0.4, end: 0.9 }, mix: 'replace', overridden: false, reverted: false },
      { edit_id: 'e2', candidate_id: 'c2', new_text: 'gone',
        selection: { start: 0.9, end: 1.3 }, mix: 'replace', overridden: false, reverted: true },
    ],
    messages: [],
  }

  it('reverts an approved edit: the line reads as shot and the original plays', async () => {
    const base = routeFetch()
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && init?.method !== 'DELETE') return ok(DETAIL)
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    window.location.hash = 'p1'
    const { container } = render(<App />)
    await screen.findByTestId('revision')
    // A reverted edit from before is not shown.
    expect(screen.queryByText('gone')).not.toBeInTheDocument()
    const video = () => container.querySelector('video') as HTMLVideoElement
    await waitFor(() => expect(video().getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'r'.repeat(64)}`))

    await userEvent.setup().click(screen.getByRole('button', { name: 'Take it out' }))

    await waitFor(() => expect(f.mock.calls.some(
      ([url, init]) => String(url).endsWith('/edits/e1/revert') && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(screen.queryByTestId('revision')).not.toBeInTheDocument())
    expect(video().getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'s'.repeat(64)}`)
  })
})

describe('App the agent (Phase 13, 20c)', () => {
  it('plans from a goal, voices it on your go, then reviews and ships', async () => {
    const calls = agent(PLAN, (text) => (text === 'go' ? PLAN_DONE : PLAN))
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)

    // W1: the goal, in Voltage's box — a turn.
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    // W3: the plan waits, in words: nothing to tick, type or run.
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
    expect(calls[0]).toMatchObject({ body: { text: 'make it 30% off' } })
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /go ahead|run/i })).not.toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()   // on the transcript line
    expect(screen.queryByText(/approve/i)).not.toBeInTheDocument()

    // Your go is the next turn.
    await user.type(screen.getByRole('textbox', TEXTBOX), 'go{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('take').some((t) => t.textContent?.includes("Brian's voice"))).toBe(true))
    expect(saidTo(calls)).toEqual(['make it 30% off', 'go'])
    expect(screen.getByText('Proposed')).toBeInTheDocument()

    // W5 (20e): hear it, then Add it, on the line itself.
    const verbs = screen.getByRole('group', { name: 'Proposal at 0:00' })
    expect(verbNames(verbs)).toEqual(['Hear it', 'Add it', 'Edit it', 'Discard'])
    await user.click(within(verbs).getByRole('button', { name: 'Add it' }))

    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src'))
      .toBe(`/api/videos/p1/artifacts/${'r'.repeat(64)}`))
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/approve'))).toBe(true)
    await waitFor(() => expect(screen.getByText('✓ In the video')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Export' })).toHaveAttribute('href', '#v/p1/export')
  })

  it('"ship it" in the composer is a turn, and the panel holds no ship card (15e, 20e)', async () => {
    const calls = agent(PLAN, (text) => (text === 'go' ? PLAN_DONE : PLAN))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')
    await screen.findByText('I read 1 line. One change does it.')
    await user.type(screen.getByRole('textbox', TEXTBOX), 'go{Enter}')
    await waitFor(() => expect(screen.getByText('Proposed')).toBeInTheDocument())

    // 20e: the proposal's verbs live on its row; the panel and the header hold no ship button.
    expect(screen.queryByRole('group', { name: 'Ready to ship' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^ship|^review/i })).toBeNull()
    expect(screen.getByRole('group', { name: 'Proposal at 0:00' })).toBeInTheDocument()

    // Said in the composer, it goes to Voltage as a turn (its ship tool ships, with the gate under Check with me).
    await user.type(screen.getByRole('textbox', TEXTBOX), 'ship it')
    await user.keyboard('{Enter}')
    await waitFor(() => expect(saidTo(calls)).toEqual(['make it 30% off', 'go', 'ship it']))
    expect(calls.some((c) => c.url.endsWith('/plans/plan1/approve'))).toBe(false)
  })

  it('adds one of two proposals; an added line can be taken out (UX-3, 20e)', async () => {
    const two = { ...PLAN_ITEM, item_id: 'i2', selection: { start: 1.5, end: 2.0 }, new_text: 'Thirty off.', mix: 'over' }
    const done = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'ready', candidate: BRIAN_TAKE }, { ...two, status: 'ready', candidate: BRIAN_TAKE }] }
    const partly = { ...done, items: [{ ...done.items[0], status: 'approved', edit_id: 'e1' }, done.items[1]] }
    const calls = agent(PLAN, (text) => (text === 'go' ? done : PLAN))
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      if (url.endsWith('/approve')) {
        calls.push({ url, body })
        return ok({ approved: [{ item_id: 'i1', edit_id: 'e1', overridden: false }], skipped: [], export: { segments: SEGMENTS, render: RENDER }, plan: partly })
      }
      if (url.endsWith('/revert')) { calls.push({ url, body }); return ok({ edit_id: 'e1', reverted: true }) }
      if (url.endsWith('/variants')) { calls.push({ url, body }); return ok({ ...PROJECT, video_id: 'p2', plan: PLAN }) }
      if (url.endsWith('/videos/p2')) return ok({ ...PROJECT, video_id: 'p2', plan: PLAN, created_at: '2026-10-04T10:00:00Z', edits: [], messages: [] })
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')
    await screen.findByText('I read 1 line. One change does it.')
    await user.type(screen.getByRole('textbox', TEXTBOX), 'go{Enter}')
    await waitFor(() => expect(screen.getAllByText('Proposed')).toHaveLength(2))
    expect(screen.getByRole('button', { name: 'Add all 2' })).toBeInTheDocument()

    // Add the first; the second stays proposed.
    await user.click(within(screen.getAllByRole('group', { name: 'Proposal at 0:00' })[0]).getByRole('button', { name: 'Add it' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/approve'))?.body).toEqual({ items: ['i1'] }))
    await waitFor(() => expect(screen.getByText('✓ In the video')).toBeInTheDocument())
    expect(screen.getAllByText('Proposed')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /add all/i })).toBeNull()

    // Take it out: the line is back to a proposal, and with nothing in the video the render and its download go.
    await user.click(screen.getByRole('button', { name: 'Take it out' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/edits/e1/revert'))).toBe(true))
    await waitFor(() => expect(screen.getAllByText('Proposed')).toHaveLength(2))
  })

  it('shows what a line needs you for, in the card and on the line; the answer is the next turn', async () => {
    const needs = { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, status: 'needs-you', question: {
      type: 'question', question: "The new line runs 1.1 s long and there's no pause after it to run into.", text: 'x', mix: 'replace',
      options: [
        { label: 'Use a shorter line: “30% off today.”', fit: null, mix: null, warning: null, text: '30% off today.' },
        { label: 'Speed it up to fit (1.3× speed)', fit: 'stretch', mix: null, warning: null },
      ] } }] }
    const calls = agent(needs, (text) => (text === 'make it 30% off' ? needs : PLAN_DONE))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')

    expect(await screen.findByText('Waiting on you')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /use a shorter line/i })).not.toBeInTheDocument()

    await user.type(screen.getByRole('textbox', TEXTBOX), 'Use the shorter line{Enter}')
    await waitFor(() => expect(screen.getByText('Proposed')).toBeInTheDocument())
    expect(saidTo(calls)).toEqual(['make it 30% off', 'Use the shorter line'])
  })

  it('remembers Just do it, and under it the turn comes back voiced', async () => {
    // Under Just do it Voltage voices within the turn: the plan arrives done, no go needed.
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await justDoIt(user)
    expect(calls.find((c) => c.url.endsWith('/settings'))?.body).toEqual({ autonomy: 'draft' })
    expect(screen.getByRole('button', { name: /^just do it\./i })).toBeInTheDocument()   // the header's autonomy word

    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')

    await waitFor(() => expect(screen.getAllByTestId('take').some((t) => t.textContent?.includes("Brian's voice"))).toBe(true))
    expect(saidTo(calls)).toEqual(['make it 30% off'])
  })

  it('takes in a turn that shipped on its own: the render plays and a note in the pane says what went in, with Export at hand (20d, Volt)', async () => {
    // Under Just do it Voltage ships inside the turn; the plan comes back with the line approved.
    const calls = agent(PLAN_APPROVED)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachEditor(user)
    await justDoIt(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off and ship it{Enter}')

    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src'))
      .toBe(`/api/videos/p1/artifacts/${'r'.repeat(64)}`))
    expect(calls.some((c) => c.url.endsWith('/approve'))).toBe(false)   // Voltage shipped; the panel only rendered
    const note = await screen.findByTestId('shipped')
    expect(note).toHaveTextContent('1 line went in on this turn')
    expect(within(note).getByRole('link', { name: 'Export →' })).toHaveAttribute('href', '#v/p1/export')
    expect(within(note).getByRole('link', { name: 'Download the file' })).toHaveAttribute('download', 'sample-ad-edited.mp4')
    expect(screen.getByText('✓ In the video')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Ship/ })).not.toBeInTheDocument()
  })

  it('asks one thing, and the answer — a pick or "go" — is the next turn', async () => {
    const calls = agent(PLAN_CLARIFYING, (text) => (text === 'make it 30% off' ? PLAN_CLARIFYING : PLAN))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')

    const ask = await screen.findByTestId('clarify')
    expect(ask).toHaveTextContent('Who speaks for the brand?')
    expect(ask).toHaveTextContent('My guess is The Shopkeeper.')

    await user.click(within(ask).getByRole('button', { name: 'The Customer' }))

    await waitFor(() => expect(saidTo(calls)).toEqual(['make it 30% off', 'The Customer']))
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()   // on the transcript line
  })

  it('Hear it on a proposal plays the take in place, over the original when nothing is rendered yet', async () => {
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')
    const verbs = await screen.findByRole('group', { name: 'Proposal at 0:00' })

    await user.click(within(verbs).getByRole('button', { name: 'Hear it' }))

    // The video runs from where the take starts; the take's audio plays over it.
    const video = container.querySelector('video') as HTMLVideoElement
    expect(video.currentTime).toBeCloseTo(0.4)
    expect(within(verbs).getByRole('button', { name: 'Stop' })).toHaveAttribute('aria-pressed', 'true')
    expect(calls.length).toBeGreaterThan(0)
  })

  it('stands by while you edit a line, and offers no wording of its own', async () => {
    agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await user.click(screen.getByText('Get 20% off today only.'))
    expect(screen.getByText(/standing by/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ask voltage for wording/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /runs long/i })).not.toBeInTheDocument()
  })

  it('changes the plan in words from the box: another turn on the same plan (UX-2, 20c)', async () => {
    const calls = agent(PLAN, (text) => (text === 'not that one' ? PLAN_REVISED : PLAN))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')
    await screen.findByText('Planned')

    const box = screen.getByRole('textbox', TEXTBOX)
    expect(box).toHaveAttribute('placeholder', expect.stringContaining('Say what to change'))
    await user.type(box, 'not that one{Enter}')

    await waitFor(() => expect(saidTo(calls)).toEqual(['make it 30% off', 'not that one']))
    expect(calls[1].body).toEqual({ text: 'not that one' })
    expect((await screen.findAllByText('Left the change out.')).length).toBeGreaterThan(0)
    await waitFor(() => expect(screen.queryByText('Planned')).not.toBeInTheDocument())
  })

  it('reopens a project with its plan', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1')) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', edits: [], messages: [{ role: 'user', text: 'make it 30% off' }],
          settings: { autonomy: 'ask' }, plan: PLAN_DONE })
      }
      return base(url, init)
    }))
    window.location.hash = 'p1'
    render(<App />)
    // The voices arrive on their own request, so the take's voice name follows a beat after the take.
    await waitFor(() => expect(screen.getAllByTestId('take').some((t) => t.textContent?.includes("Brian's voice"))).toBe(true))
    expect(screen.queryByTestId('first-read')).not.toBeInTheDocument()
  })

})

describe('App fit notes (Phase 14)', () => {
  it('shows how the take was fitted under the line', async () => {
    const fitted = { ...BRIAN_TAKE, fit_notes: ['nearest of 3 takes', 'trimmed 120 ms of pauses'] }
    agent({ ...PLAN_DONE, items: [{ ...PLAN_ITEM, status: 'ready', candidate: fitted }] })
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await hearNewWords(user)
    const take = await screen.findByTestId('take')
    expect(take).toHaveTextContent('Trimmed 120 ms of pauses')
  })
})

describe('App: a fresh upload after another project', () => {
  it('shows the first reply of the new project (the thread\'s high-water mark is per project)', async () => {
    // Open p1, which already holds five messages; then upload again and send a turn: its reply is seq 2 of the new project.
    const calls = agent(PLAN_DONE)
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', edits: [], settings: { autonomy: 'ask' },
          messages: [1, 2, 3, 4, 5].map((seq) => ({ role: seq % 2 ? 'user' : 'assistant', text: `earlier ${seq}`, kind: 'say', seq })) })
      }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    window.location.hash = 'p1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('earlier 5')
    await user.click(screen.getByRole('link', { name: /all projects/i }))
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'make it 30% off{Enter}')
    await waitFor(() => expect(saidTo(calls)).toEqual(['make it 30% off']))
    expect(await screen.findByText('I read 1 line. One change does it.')).toBeInTheDocument()
  })
})

describe('App: audio lines coexist (20f)', () => {
  it('shows an added line and a proposal at the same moment as two rows, and Edit it on either is a redo turn', async () => {
    const detail = { ...PROJECT, statements: [], transcript: [], created_at: '2026-10-02T08:00:00Z', settings: { autonomy: 'draft' }, messages: [],
      edits: [{ edit_id: 'e1', candidate_id: 'c1', selection: { start: 0.4, end: 6.9 }, new_text: 'Golden sands, endless sunsets.', mix: 'layer', old_text: '', reverted: false }],
      plan: { ...PLAN, status: 'done', items: [{ ...PLAN_ITEM, item_id: 'i2', selection: { start: 0.4, end: 1.8 }, old_text: '', new_text: 'Woohoo!', mix: 'layer', status: 'ready',
        candidate: { ...BRIAN_TAKE, candidate_id: 'c2', plan: { ...BRIAN_TAKE.plan, selection: { start: 0.4, end: 1.8 }, new_text: 'Woohoo!', mix: 'layer' } } }] } }
    const calls = agent(detail.plan)
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) return ok(detail)
      return base(url, init)
    }))
    window.location.hash = 'p1'
    const user = userEvent.setup()
    render(<App />)
    const added = await screen.findByRole('listitem', { name: 'Added line at 0:00' })
    const proposed = screen.getByRole('listitem', { name: 'Proposed line at 0:00' })
    expect(added).toHaveTextContent('Golden sands, endless sunsets.')
    expect(proposed).toHaveTextContent('Woohoo!')
    expect(added).toHaveTextContent('with 1 other line at this moment')

    await user.click(within(proposed).getByRole('button', { name: 'Edit it' }))
    await user.click(screen.getByRole('button', { name: 'Change the words' }))   // Volt: Edit it opens the depth first
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Woohoo! Yeah!{Enter}')
    await waitFor(() => expect(saidTo(calls)).toEqual(["Voice i2 again as “Woohoo! Yeah!”, in Brian's voice"]))   // the editor opens on the take's own voice

    await user.click(within(screen.getByRole('listitem', { name: 'Added line at 0:00' })).getByRole('button', { name: 'Edit it' }))
    const box2 = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box2)
    await user.type(box2, 'Golden sands.{Enter}')
    await waitFor(() => expect(saidTo(calls).at(-1)).toBe('Redo the added line at 0:00 (“Golden sands, endless sunsets.”, e1) as “Golden sands.”: voice it at 0:00–0:06, over the picture, ship it and take e1 out'))
  })
})

describe('App: the server\'s edits win after a turn, and a line can be mixed under the words (20g)', () => {
  const e1 = { edit_id: 'e1', candidate_id: 'c1', selection: { start: 0.4, end: 6.9 }, new_text: 'Golden sands.', mix: 'layer', old_text: '', reverted: false }
  const e2 = { edit_id: 'e2', candidate_id: 'c2', selection: { start: 0.4, end: 1.8 }, new_text: 'Woohoo!', mix: 'layer', old_text: '', reverted: false }
  const silent = { ...PROJECT, statements: [], transcript: [], created_at: '2026-10-02T08:00:00Z', settings: { autonomy: 'draft' }, messages: [], plan: null }

  it('drops a row Voltage undid during the turn, and renders again', async () => {
    let edits = [e1, e2]
    const calls = agent({ ...PLAN, status: 'done', items: [] }, () => { edits = [e1, { ...e2, reverted: true }]; return { ...PLAN, status: 'done', items: [] } })
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) return ok({ ...silent, edits })
      if (url.endsWith('/export')) { calls.push({ url, body: null }); return ok({ segments: SEGMENTS, render: RENDER }) }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    window.location.hash = 'p1'
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findAllByRole('listitem', { name: 'Added line at 0:00' })).toHaveLength(2)
    const exports = () => calls.filter((c) => c.url.endsWith('/export')).length
    const before = exports()
    await user.type(screen.getByRole('textbox', TEXTBOX), 'take the cheer out{Enter}')
    await waitFor(() => expect(screen.getAllByRole('listitem', { name: 'Added line at 0:00' })).toHaveLength(1))
    expect(screen.queryByText('Woohoo!')).toBeNull()
    expect(exports()).toBe(before + 1)   // the render follows the edits
  })

  it('Make it background relevels an added line: the row swaps to the new edit and the video renders again', async () => {
    const base = routeFetch()
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) return ok({ ...silent, edits: [e1, e2] })
      if (url.endsWith('/edits/e2/level')) {
        expect(JSON.parse(String(init?.body))).toEqual({ level_db: -12 })
        return ok({ edit_id: 'e3', reverted: 'e2', candidate: { ...CANDIDATE, candidate_id: 'c3', plan: { ...CANDIDATE.plan, selection: { start: 0.4, end: 1.8 }, new_text: 'Woohoo!', mix: 'layer', level_db: -12 } } })
      }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    window.location.hash = 'p1'
    const user = userEvent.setup()
    render(<App />)
    const rows = await screen.findAllByRole('listitem', { name: 'Added line at 0:00' })
    await user.click(within(rows[1]).getByRole('button', { name: 'Make it background' }))
    await waitFor(() => expect(within(screen.getAllByRole('listitem', { name: 'Added line at 0:00' })[1]).getByText(/background \(-12 dB\)/)).toBeInTheDocument())
    expect(f.mock.calls.filter(([url]) => String(url).endsWith('/export')).length).toBeGreaterThanOrEqual(2)
  })
})

describe('App panel order', () => {
  it('opens a clip with no speech in the workspace: Voltage says what it saw, the place editor is the transcript (UX-5, UX-7c)', async () => {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos') && init?.method === 'POST') return ok({ ...PROJECT, transcript: [], statements: [], frames: [{ index: 0, at: 0.3 }, { index: 1, at: 1.2 }, { index: 2, at: 2.0 }] })
      if (url.endsWith('/reading')) return ok({ opening: 'No one speaks. A beach at dusk.', roles: [], sight: { opening: 'No one speaks. A beach at dusk.', setting: 'A wide beach at dusk', mood: 'calm', people: 'two, far off', text_on_screen: '', place_guess: 'Goa', confidence: 'medium', beats: [] } })
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    expect(await screen.findByText(/No one speaks\. A beach at dusk\./)).toBeInTheDocument()
    expect(screen.getByTestId('sight')).toHaveTextContent('A wide beach at dusk')
    expect(screen.getByTestId('sight')).toHaveTextContent('The place: Goa')
    expect(screen.getByRole('button', { name: 'Looks right' })).toBeInTheDocument()
    expect(screen.getByText('Where should the voice-over go?')).toBeInTheDocument()
    // Volt: an example chip is sent as a turn.
    await user.click(screen.getByRole('button', { name: 'Introduce the place' }))
    expect(await screen.findByText('Introduce the place')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Introduce the place' })).toBeNull()
  })

  it('places a voice-over on a clip with no speech: the span and the words go to Voltage in a sentence (UX-5)', async () => {
    const calls = agent()
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos') && init?.method === 'POST') return ok({ ...PROJECT, transcript: [], statements: [], frames: [{ index: 0, at: 0.3 }] })
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    const editor = await screen.findByTestId('place-editor')
    await user.type(within(editor).getByRole('textbox', { name: 'Words for the voice-over' }), 'Welcome to Goa.')
    await user.click(within(editor).getByRole('button', { name: 'Voice it' }))
    await waitFor(() => expect(saidTo(calls)).toEqual(['Add “Welcome to Goa.” at 0:00–0:02, over the picture']))
  })
})

describe('App with Voltage as an agent (Phase 20a)', () => {
  const STEPS = [
    { role: 'assistant', text: 'Listened: no one speaks', kind: 'step', seq: 2 },
    { role: 'assistant', text: 'Looked through 25 voices', kind: 'step', seq: 3 },
    { role: 'assistant', text: 'Voiced “Welcome to Goa.” with Varsha · warm and unhurried', kind: 'step', cost: 0.03, seq: 4 },
    { role: 'assistant', text: 'One line over the opening shot, in Varsha\'s voice. Hear it below.', kind: 'say', seq: 5 },
  ]

  function agentRoutes() {
    const base = routeFetch()
    const calls: { url: string; body: unknown }[] = []
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      if (url.endsWith('/videos/p1') || (url.endsWith('/videos') && init?.method === 'POST')) return ok({ ...PROJECT, edits: [], messages: [] })
      if (url.endsWith('/turns') && init?.method === 'POST') { calls.push({ url, body }); return ok(JOB_ACCEPTED) }
      if (url.includes('/jobs/')) return ok({ ...JOB_TURN, result: { type: 'turn', plan: PLAN_DONE, reply: STEPS[3].text, question: null } })
      if (url.includes('/messages?after=')) {
        const after = Number(url.split('after=')[1])
        return ok(STEPS.filter((m) => m.seq > after))
      }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    return calls
  }

  it('sends the composer to a turn, shows each step as it comes, then the take on its row — and no voice picker', async () => {
    const calls = agentRoutes()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    expect(screen.queryByRole('combobox', { name: /default voice/i })).toBeNull()
    expect(screen.queryByText('Default voice')).toBeNull()

    await user.type(screen.getByRole('textbox', TEXTBOX), 'Describe the place in an Indian voice{Enter}')
    expect(calls).toEqual([{ url: '/api/videos/p1/turns', body: { text: 'Describe the place in an Indian voice' } }])
    expect(screen.getByText('Describe the place in an Indian voice')).toBeInTheDocument()

    const list = await screen.findByRole('list', { name: 'What Voltage did' })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '├Listened: no one speaksfree', '├Looked through 25 voicesfree', '└Voiced “Welcome to Goa.” with Varsha · warm and unhurried$0.03',
    ])
    expect(screen.getByTestId('trace')).toHaveTextContent('Trace · 3 steps')
    expect(await screen.findByText("One line over the opening shot, in Varsha's voice. Hear it below.")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Proposed')).toBeInTheDocument())
    // 20e: the verbs are on the proposal's row; the panel holds no ship card.
    expect(screen.queryByRole('group', { name: 'Ready to ship' })).toBeNull()
    expect(screen.getByRole('group', { name: 'Proposal at 0:00' })).toBeInTheDocument()
    expect(screen.queryByTestId('turn-working')).toBeNull()
  })

  it('answers Voltage\'s question with another turn', async () => {
    const calls = agentRoutes()
    const asked = { ...PLAN, status: 'clarifying', question: { text: 'Voice “Welcome to Goa.” with Varsha\'s voice, about $0.03?', options: ['Go ahead', 'Not yet'], guess: 'Go ahead', gate: true } }
    const f = vi.mocked(fetch as unknown as ReturnType<typeof vi.fn>)
    const inner = f.getMockImplementation()! as (url: string, init?: RequestInit) => Promise<Response>
    f.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes('/jobs/') && calls.length === 1) return ok({ ...JOB_TURN, result: { type: 'turn', plan: asked, reply: '', question: asked.question } })
      return inner(url, init)
    })
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.type(screen.getByRole('textbox', TEXTBOX), 'Describe the place{Enter}')
    const go = await screen.findByRole('button', { name: 'Go ahead' })
    expect(screen.getByTestId('clarify')).toHaveTextContent('Say go, or pick one.')
    await user.click(go)
    expect(calls.map((c) => (c.body as { text: string }).text)).toEqual(['Describe the place', 'Go ahead'])
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
    const box = screen.getByRole('textbox', TEXTBOX)
    expect(box).toHaveFocus()
    expect(box).toHaveValue('')
    await user.keyboard('a/b')
    expect(box).toHaveValue('a/b')
  })
})

describe('App: the line is the unit (UX-1)', () => {
  it('adds a take from the row: its plan item is approved and rendered, and the line shows it Added with Take it out', async () => {
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await hearNewWords(user)
    await screen.findByTestId('take')

    await user.click(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Add it' }))

    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/plans/plan1/approve'))?.body).toEqual({ items: ['i1'] }))
    await waitFor(() => expect(screen.getByText('✓ In the video')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Take it out' })).toBeInTheDocument()
    expect(screen.queryByTestId('take')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ship-sheet')).not.toBeInTheDocument()   // Add it is one line; no sheet
  })

  it('asks for another take in words', async () => {
    const calls = agent(PLAN_DONE)
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await hearNewWords(user)
    await screen.findByTestId('take')

    // Volt: Edit it opens the proposal in place; Voice it again asks Voltage for the take again, said the same way.
    await user.click(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Edit it' }))
    await user.click(within(screen.getByTestId('depth')).getByRole('button', { name: 'Voice it again' }))

    await waitFor(() => expect(saidTo(calls).at(-1)).toBe('Voice i1 again, said the same way'))
  })

  it('Discard on a line as shot proposes removing it: struck through, Remove it at hand (20e)', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Discard' }))

    await waitFor(() => expect(screen.getByText('Proposed')).toBeInTheDocument())
    expect(screen.getByText('Get 20% off today only.').tagName).toBe('DEL')
    expect(f.mock.calls.some(([url, init]) => String(url).endsWith('/lines/remove') && init?.method === 'POST')).toBe(true)
    expect(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Remove it' })).toBeInTheDocument()
    expect(f.mock.calls.some(([url]) => String(url).endsWith('/export'))).toBe(false)   // nothing rendered: nothing is in the video yet
  })

  it('adds a line after a line, over the picture by default: said to Voltage', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Add a line after' }))
    await user.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Hurry, it ends Sunday.{Enter}')

    await waitFor(() => expect(saidTo(calls)).toEqual(['Add “Hurry, it ends Sunday.” after the line at 0:00, over the picture']))
  })

  it('adds a line that holds the picture: said so', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)

    await user.click(screen.getByRole('button', { name: /^\+ add a line$/i }))
    await user.click(screen.getByRole('button', { name: 'Hold the picture' }))
    await user.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Bye!{Enter}')

    await waitFor(() => expect(saidTo(calls)).toEqual(['Add “Bye!” after the line at 0:00, holding the picture']))
  })

  it('plays a take in place: the video runs from the line with the take over it', async () => {
    agent(PLAN_DONE)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachGoal(user)
    await hearNewWords(user)
    await screen.findByTestId('take')
    const verbs = screen.getByRole('group', { name: 'Proposal at 0:00' })

    await user.click(within(verbs).getByRole('button', { name: 'Hear it' }))

    const video = container.querySelector('video') as HTMLVideoElement
    expect(video.currentTime).toBe(0.4)
    expect(video.muted).toBe(true)   // a replacement: the original's words are off
    expect(within(verbs).getByRole('button', { name: 'Stop' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('App: shifting original speech (UX-1c)', () => {
  it('shifts a line to a typed time: room tone where it was, the words over the picture there, undo for both', async () => {
    const f = routeFetch()
    vi.stubGlobal('fetch', f)
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:00' })).getByRole('button', { name: 'Shift to a time…' }))
    const box = screen.getByRole('textbox', { name: 'Starts at' })
    await user.clear(box)
    await user.type(box, '0:01.00')
    await user.click(screen.getByRole('button', { name: 'Put it here' }))

    await waitFor(() => expect(f.mock.calls.some(([url, init]) => String(url).endsWith('/lines/shift')
      && JSON.parse(String(init?.body)).to === 1)).toBe(true))
    // Where it was, and its own row where it now plays.
    expect(await screen.findByText('Moved away')).toBeInTheDocument()
    expect(screen.getByText(/Moved to 0:01\.00/)).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: 'Moved line at 0:01' })).toHaveTextContent('Get 20% off today only.')
    expect(screen.getByText('Moved')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Put it back' }))
    await waitFor(() => expect(f.mock.calls.some(([url]) => String(url).endsWith('/edits/e8/revert'))).toBe(true))
    await waitFor(() => expect(screen.queryByText('Moved')).not.toBeInTheDocument())
    expect(screen.queryByText('Moved away')).not.toBeInTheDocument()
  })
})

describe('App: the monitor (UX-7b)', () => {
  it('captions the picture with the line at the playhead, the changed words lit, and draws the lines on the timeline', async () => {
    agent(PLAN_DONE)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await reachEditor(user)
    // At rest at 0:00 the picture is bare; once it moves, the line at the playhead is on it.
    expect(screen.queryByTestId('caption')).not.toBeInTheDocument()
    const video = container.querySelector('video') as HTMLVideoElement
    video.currentTime = 1
    fireEvent.timeUpdate(video)
    expect(screen.getByTestId('caption')).toHaveTextContent('Get 20% off today only.')
    expect(screen.queryByTestId('marker')).toBeNull()   // nothing proposed or in the video yet
    // A take in hand shows its new words on the picture.
    await user.click(screen.getAllByText('Get 20% off today only.').find((el) => el.tagName === 'BUTTON')!)
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await user.clear(box)
    await user.type(box, 'Get 30% off today only.{Enter}')
    await screen.findByTestId('take')
    fireEvent.timeUpdate(video)
    expect(screen.getByTestId('caption').querySelector('ins')).toBeTruthy()
    // Volt: the proposal is a volt mark on the scrubber.
    expect(screen.getAllByTestId('marker').map((m) => m.getAttribute('data-tone'))).toEqual(['volt'])
  })
})

describe('App: moving audio on the timeline (UX-1b)', () => {
  it('moves a take to a typed time and shows the moved take under the line', async () => {
    agent(PLAN_DONE)
    const calls: { url: string; body: unknown }[] = []
    const base = fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/candidates/c1/move')) {
        calls.push({ url, body: JSON.parse(String(init?.body)) })
        return ok({ ...CANDIDATE, candidate_id: 'c2', plan: { ...CANDIDATE.plan, selection: { start: 1.5, end: 2.0 }, fit: 'start' }, fit_notes: ['moved to 0:01'] })
      }
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await hearNewWords(user)
    const place = within(await screen.findByTestId('take')).getByTestId('place')

    await user.click(screen.getByRole('button', { name: 'Tracks' }))   // Volt: the placing bar lives in the tracks panel
    await user.click(within(place).getByRole('button', { name: 'Move' }))
    expect(screen.getByRole('slider', { name: 'Where the take starts' })).toBeInTheDocument()
    const field = within(screen.getByTestId('place')).getByRole('textbox', { name: 'Starts at' })
    await user.clear(field)
    await user.type(field, '1.5{Enter}')

    await waitFor(() => expect(calls).toEqual([{ url: '/api/videos/p1/candidates/c1/move', body: { start: 1.5 } }]))
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
      if (url.endsWith('/videos/p1')) {
        return ok({ ...PROJECT, created_at: '2026-10-02T08:00:00Z', messages: [{ role: 'user', text: 'x' }], settings: { autonomy: 'ask' },
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

  it('adds a line at a chosen time: said to Voltage with the time', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.click(screen.getByRole('button', { name: /^\+ add a line$/i }))
    await user.type(screen.getByRole('textbox', { name: 'Starts at' }), '1.1')
    await user.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Welcome.{Enter}')
    await waitFor(() => expect(saidTo(calls)).toEqual(['Add “Welcome.” at 0:01, over the picture']))
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
    const door = await screen.findByRole('link', { name: /continue with google/i })
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
    expect(await screen.findByRole('link', { name: 'Account' })).toHaveTextContent('A')
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    await screen.findByText('Get 20% off today only.')
    const upload = calls.find((c) => c.url.endsWith('/videos') && c.init?.method === 'POST')
    expect((upload!.init!.headers as Record<string, string>)['X-Requested-With']).toBe('voltage')

    // Volt: Sign out is on the Settings page.
    act(() => { window.location.hash = 'settings' })
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(calls.some((c) => c.url.endsWith('/auth/logout') && c.init?.method === 'POST')).toBe(true)
    expect(await screen.findByRole('link', { name: /continue with google/i })).toBeInTheDocument()
  })

  it('goes back to the door when the session ends', async () => {
    const base = routeFetch()
    const gone = { ok: false, status: 401, json: async () => ({ detail: 'Sign in to continue.' }), text: async () => JSON.stringify({ detail: 'Sign in to continue.' }) } as Response
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/me')) return ok(ME)
      if (url.endsWith('/videos') && init?.method === 'POST') return gone
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /sample ad/i }))
    expect(await screen.findByRole('link', { name: /continue with google/i })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Your session ended')
  })
})

describe('App: what Voltage may do (20d)', () => {
  it('opens the sheet from the header and saves the cap and the effort as they change', async () => {
    const calls = agent()
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.click(screen.getByRole('button', { name: /what voltage may do/i }))
    const sheet = await screen.findByRole('dialog', { name: 'What Voltage may do' })
    expect(within(sheet).getByRole('button', { name: 'Check with me' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(sheet).getByRole('button', { name: 'Thorough' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/settings'))?.body).toEqual({ effort: 'xhigh' }))
    const cap = within(sheet).getByLabelText('One turn may spend')
    await user.clear(cap)
    await user.type(cap, '0.8{Enter}')
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/settings')).map((c) => c.body)).toContainEqual({ turn_usd: 0.8 }))
    await user.click(within(sheet).getByRole('button', { name: 'Just do it' }))
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/settings')).map((c) => c.body)).toContainEqual({ autonomy: 'draft' }))
    expect(screen.getByRole('group', { name: 'How much Voltage does on its own' })).toBeInTheDocument()
  })
})

describe('App: the guided run and the keyboard sheet (Tutorial map and Help)', () => {
  it('offers the tour on Home; Start opens the sample as a tutorial video with the goal in the box and the welcome card', async () => {
    const base = routeFetch()
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/tutorial') && init?.method === 'POST') { calls.push(url); return ok({ ...PROJECT, settings: { autonomy: 'ask', tutorial: true }, reading: READING }) }
      if (url.endsWith('/videos/p1') && !init?.method) return ok({ ...PROJECT, settings: { autonomy: 'ask', tutorial: true }, reading: READING, created_at: '2026-10-19T08:00:00Z', edits: [], messages: [] })
      if (url.includes('/me/onboarding')) return ok({ tour: { step: 0, finished: false, skipped: false }, tips: [], checklist: [], checklist_hidden: false })
      return base(url, init)
    }))
    const user = userEvent.setup()
    render(<App />)
    const offer = await screen.findByTestId('tour-offer')
    await user.click(within(offer).getByRole('button', { name: '⚡ Start the tour' }))
    await waitFor(() => expect(calls).toEqual(['/api/tutorial']))
    await waitFor(() => expect(window.location.hash).toBe('#v/p1'))
    await waitFor(() => expect(screen.getByRole('textbox', TEXTBOX)).toHaveValue('Make the offer 30% off'))
    expect(await screen.findByRole('dialog', { name: /welcome|change what a video/i })).toBeInTheDocument()
    // The checklist stays out of the tutorial video.
    expect(screen.queryByRole('button', { name: /get started/i })).toBeNull()
  })

  it('opens the keyboard sheet on ? in the editor, and closes it on Escape', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachGoal(user)
    await user.click(document.body)
    await user.keyboard('?')
    expect(await screen.findByRole('dialog', { name: 'Keyboard' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Keyboard' })).toBeNull())
  })
})

describe('App: renders land in the order they were asked for (bug 1)', () => {
  /** /export answers held until the test releases them, by request id and mode. */
  function heldRenders(edits: unknown[], plan: unknown = null) {
    const base = routeFetch()
    const held: { id: number; proposals: boolean; release: (sha: string) => void }[] = []
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) {
        return ok({ ...PROJECT, created_at: '2026-10-19T08:00:00Z', settings: { autonomy: 'ask' }, edits, plan, messages: [{ role: 'user', text: 'x' }] })
      }
      if (url.endsWith('/export')) {
        const body = JSON.parse(String(init?.body ?? '{}'))
        return new Promise<Response>((resolve) => {
          held.push({ id: body.request_id, proposals: !!body.with_proposals,
            release: (sha) => resolve(ok({ segments: SEGMENTS, render: { ...RENDER, sha256: sha.repeat(64) }, edit_hash: sha, request_id: body.request_id })) })
        })
      }
      if (url.endsWith('/edits/e1/level')) {
        return ok({ edit_id: 'e2', reverted: 'e1', candidate: { ...CANDIDATE, plan: { ...CANDIDATE.plan, mix: 'layer', level_db: -12 } } })
      }
      return base(url, init)
    })
    vi.stubGlobal('fetch', f)
    return held
  }
  const LAYER = { edit_id: 'e1', candidate_id: 'c1', new_text: 'Hello there', selection: { start: 0.4, end: 0.9 }, mix: 'layer', overridden: false, reverted: false }

  it('drops an older final render that finishes after a newer one; Rendering… clears only with the newer', async () => {
    const held = heldRenders([LAYER])
    window.location.hash = 'v/p1'
    const user = userEvent.setup()
    const { container } = render(<App />)
    await waitFor(() => expect(held).toHaveLength(1))                       // opening renders the edits (request 1)
    expect(screen.getByRole('link', { name: /rendering/i })).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /make it background/i }))   // the edit set changes: request 2
    await waitFor(() => expect(held).toHaveLength(2))
    held[1].release('b')                                                     // the newer finishes first
    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'b'.repeat(64)}`))
    expect(screen.getByRole('link', { name: 'Export' })).toBeInTheDocument()  // the status is the latest's
    held[0].release('a')                                                     // the older lands late: dropped
    await new Promise((r) => setTimeout(r, 50))
    expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'b'.repeat(64)}`)
    expect(screen.getByRole('link', { name: 'Export' })).toBeInTheDocument()
  })

  it('asks for the preview again while an older one runs, and shows only the latest', async () => {
    const plan = { ...PLAN_DONE, items: [{ ...PLAN_ITEM, status: 'ready', mix: 'layer', candidate: { ...BRIAN_TAKE, plan: { ...BRIAN_TAKE.plan, mix: 'layer' } } }] }
    const held = heldRenders([], plan)
    window.location.hash = 'v/p1'
    const user = userEvent.setup()
    const { container } = render(<App />)
    const withProposals = await screen.findByRole('button', { name: /with proposals/i })
    await user.click(withProposals)
    await waitFor(() => expect(held.filter((h) => h.proposals)).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: /as shot/i }))
    await user.click(screen.getByRole('button', { name: /with proposals/i }))
    // Before the fix a second ask was ignored while the first ran, and the status could never clear.
    await waitFor(() => expect(held.filter((h) => h.proposals)).toHaveLength(2))
    const [older, newer] = held.filter((h) => h.proposals)
    older.release('c')
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.getByTestId('mode-badge')).toBeInTheDocument()
    expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src')).not.toBe(`/api/videos/p1/artifacts/${'c'.repeat(64)}`)
    newer.release('d')
    await waitFor(() => expect((container.querySelector('video') as HTMLVideoElement).getAttribute('src')).toBe(`/api/videos/p1/artifacts/${'d'.repeat(64)}`))
  })
})


describe('App: Edited, As shot, With proposals (2026-10-19)', () => {
  const EDITS = [
    { edit_id: 'e1', candidate_id: 'c1', new_text: 'Get 30% off today only.', selection: { start: 0, end: 2.3 }, mix: 'replace', overridden: false, reverted: false },
    { edit_id: 'e2', candidate_id: 'c2', new_text: 'Hurry!', selection: { start: 1.5, end: 2.0 }, mix: 'layer', overridden: false, reverted: false },
  ]
  const READY = { ...PLAN_DONE, items: [{ ...PLAN_ITEM, item_id: 'i5', selection: { start: 0.2, end: 0.6 }, mix: 'layer', new_text: 'Wow', status: 'ready', candidate: { ...BRIAN_TAKE, candidate_id: 'c5', plan: { ...BRIAN_TAKE.plan, mix: 'layer', selection: { start: 0.2, end: 0.6 } } } }] }
  function opened(edits: unknown[], plan: unknown = null) {
    const base = routeFetch()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/videos/p1') && !init?.method) return ok({ ...PROJECT, created_at: '2026-10-19T08:00:00.000Z', settings: { autonomy: 'ask' }, edits, plan, messages: [{ role: 'user', text: 'x' }] })
      return base(url, init)
    }))
    window.location.hash = 'v/p1'
  }
  const badge = () => screen.getByTestId('mode-badge')

  it('names the modes Edited, With proposals and As shot, and the badge counts what each leaves out', async () => {
    opened(EDITS, READY)
    const user = userEvent.setup()
    render(<App />)
    const play = await screen.findByRole('group', { name: 'Play' })
    await waitFor(() => expect(within(play).getAllByRole('button').map((b) => b.textContent)).toEqual(['Edited', 'With proposals', 'As shot']))
    await waitFor(() => expect(badge()).toHaveTextContent('Edited · 1 proposal not included'))
    await user.click(within(play).getByRole('button', { name: 'As shot' }))
    expect(badge()).toHaveTextContent('As shot · 2 changes hidden')
  })

  it('makes the transcript and the A2 lane follow the mode, and O flips Edited ↔ As shot', async () => {
    opened(EDITS)
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edited' })).toHaveAttribute('aria-pressed', 'true'))
    // Edited: the replaced line shows its new words; the added line is in the video.
    expect(screen.getByTestId('revision')).toHaveTextContent('30%')
    const added = screen.getByRole('listitem', { name: 'Added line at 0:01' })
    expect(within(added).queryByTestId('not-in-version')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Tracks' }))
    expect(screen.getByTestId('lane-a2')).not.toHaveAttribute('data-muted')

    await user.click(document.body)
    await user.keyboard('o')
    expect(screen.getByRole('button', { name: 'As shot' })).toHaveAttribute('aria-pressed', 'true')
    // As shot: the replaced line reads as shot; the added line dims with "not in this version"; A2 greys out.
    expect(screen.queryByTestId('revision')).toBeNull()
    expect(screen.getByRole('listitem', { name: /Line at 0:00/ })).toHaveTextContent('Get 20% off today only.')
    expect(within(screen.getByRole('listitem', { name: /Line at 0:00/ })).getByTestId('not-in-version')).toBeInTheDocument()
    const dimmed = screen.getByRole('listitem', { name: 'Added line at 0:01' })
    expect(within(dimmed).getByTestId('not-in-version')).toHaveTextContent('not in this version')
    expect(dimmed).toHaveClass('opacity-50')
    expect(screen.getByTestId('lane-a2')).toHaveAttribute('data-muted', 'true')

    await user.keyboard('O')
    expect(screen.getByRole('button', { name: 'Edited' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('revision')).toHaveTextContent('30%')
  })

  it('shows a removed line with its words again in As shot', async () => {
    opened([{ edit_id: 'e3', candidate_id: 'c3', new_text: '', selection: { start: 0, end: 2.3 }, mix: 'remove', overridden: false, reverted: false }])
    const user = userEvent.setup()
    render(<App />)
    const line = await screen.findByRole('listitem', { name: /Line at 0:00/ })
    await waitFor(() => expect(line.querySelector('del')).not.toBeNull())
    await user.click(screen.getByRole('button', { name: 'As shot' }))
    const asShot = screen.getByRole('listitem', { name: /Line at 0:00/ })
    expect(asShot.querySelector('del')).toBeNull()
    expect(asShot).toHaveTextContent('Get 20% off today only.')
    expect(badge()).toHaveTextContent('As shot · 1 change hidden')
  })

  it('with no live edits shows a plain As shot label instead of the switch', async () => {
    opened([])
    render(<App />)
    expect(await screen.findByTestId('as-shot-label')).toHaveTextContent('As shot')
    expect(screen.queryByRole('group', { name: 'Play' })).toBeNull()
  })

  it('keeps the moment when switching mid-playback', async () => {
    opened(EDITS)
    const user = userEvent.setup()
    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edited' })).toHaveAttribute('aria-pressed', 'true'))
    const video = () => container.querySelector('video') as HTMLVideoElement
    await user.click(screen.getAllByRole('button', { name: 'Play' }).find((b) => b.closest('section[aria-label="Monitor"]'))!)
    video().currentTime = 1.4
    fireEvent.timeUpdate(video())
    await user.click(screen.getByRole('button', { name: 'As shot' }))
    fireEvent.loadedMetadata(video())
    expect(video().currentTime).toBeCloseTo(1.4, 2)
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()   // still playing
  })
})
