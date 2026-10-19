import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectPage } from './ProjectPage'
import { unlabelledMoney } from '../lib/money'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
const DETAIL = {
  project: { project_id: 'f1', name: 'Diwali 2026', brief: 'Brand is Bhaji Cam, said BAH-jee cam.', settings: { autonomy: 'ask', turn_usd: 0.5, effort: 'high' }, ceiling_usd: 10, spent_usd: 1.94, created_at: '2026-10-18T08:00:00Z' },
  videos: [
    { video_id: 'p2', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: '2026-10-18T09:00:00Z', edits: 0, state: 'draft', last_change: '2 proposed' },
    { video_id: 'p3', project_id: 'f1', project_name: 'Diwali 2026', filename: 'shop-tour.mp4', duration: 31, created_at: '2026-10-15T09:00:00Z', edits: 2, state: 'shipped', last_change: 'Brand said as Bhaji Cam throughout' },
  ],
  voices: [
    { voice_id: 'v1', name: 'Diwali Narrator', kind: 'designed', seconds: 0, at: '2026-10-18T08:00:00.000Z', used_in: 2, consent_granted_at: null, consent_needed: false },
    { voice_id: 'v2', name: 'Deewar song', kind: 'recorded', seconds: 15, at: '2026-10-19T16:10:24.983Z', used_in: 1, consent_granted_at: '2026-10-19T16:09:46.615Z' },
    { voice_id: 'v3', name: 'Old share', kind: 'recorded', seconds: 15, at: '2026-10-19T16:10:24.983Z', consent_granted_at: null },
  ],
  files: [{ name: 'brand-guide.pdf', sha256: 'a'.repeat(64), size: 1200, kind: 'pdf', at: '2026-10-18T08:00:00Z' }],
  suggestions: [{ id: 's1', text: 'The offer ends 2 November.', why: null, video_id: 'p2', filename: 'bhaji-cam-ad.mp4', at: '2026-10-19T08:00:00Z' }],
}

function routeFetch(calls: { url: string; method: string; body?: unknown }[] = []) {
  let detail = DETAIL
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (method !== 'GET') calls.push({ url, method, body })
    if (url.endsWith('/projects/f1') && method === 'GET') return ok(detail)
    if (url.endsWith('/spend?project=f1')) return ok({ project: { spent_usd: detail.project.spent_usd, ceiling_usd: detail.project.ceiling_usd, label: `Project ${detail.project.name}` }, month: { spent_usd: 3.1, ceiling_usd: 100, label: 'October' }, binding: 'project' })
    if (url.endsWith('/projects/f1') && method === 'PATCH') { detail = { ...detail, project: { ...detail.project, ...body } }; return ok(detail.project) }
    if (url.endsWith('/projects/f1/suggestions/s1/accept')) { detail = { ...detail, project: { ...detail.project, brief: detail.project.brief + ' The offer ends 2 November.' }, suggestions: [] }; return ok(detail) }
    if (url.includes('/projects/f1?videos=') && method === 'DELETE') return ({ ok: true, status: 204, json: async () => null, text: async () => '' }) as Response
    if (url.endsWith('/projects/f1/voices/v1') && method === 'DELETE') return ({ ok: true, status: 204, json: async () => null, text: async () => '' }) as Response
    throw new Error(`unexpected ${method} ${url}`)
  })
}

describe('ProjectPage (a folder of videos)', () => {
  beforeEach(() => { window.location.hash = '#p/f1' })
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('shows the name, the tag line, the videos as cards, and what the project shares', async () => {
    vi.stubGlobal('fetch', routeFetch())
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Diwali 2026')
    expect(screen.getByText('2 videos · 3 shared voices · 1 file')).toBeInTheDocument()
    // Spend scopes: the project's spend, then the month's, each named.
    await waitFor(() => expect(screen.getByTestId('project-spend')).toHaveTextContent('$1.94 spent in this project · $3.10 of your $100 in October'))
    const cards = screen.getAllByRole('link', { name: /\.mp4/ })
    expect(cards.map((c) => c.getAttribute('href'))).toEqual(['#v/p2', '#v/p3'])
    expect(screen.getAllByText('2 proposed').length).toBeGreaterThan(0)
    expect(screen.getByText('Exported')).toBeInTheDocument()
    expect(screen.getByTestId('brief')).toHaveTextContent('Voltage reads this in every turn')
    expect(screen.getByRole('textbox', { name: 'Project brief' })).toHaveValue('Brand is Bhaji Cam, said BAH-jee cam.')
    expect(within(screen.getByTestId('shared-voices')).getByText('Diwali Narrator')).toBeInTheDocument()
    expect(within(screen.getByTestId('files')).getByText('brand-guide.pdf')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Project Diwali 2026: $1.94 of its $10 project ceiling' })).toHaveAttribute('aria-valuenow', '19')
    expect(unlabelledMoney(document.body)).toEqual([])
    expect(screen.getByText(/planned as a batch turn/)).toBeInTheDocument()
  })

  it('shows the project ceiling meter only when one is set', async () => {
    const plain = { ...DETAIL, project: { ...DETAIL.project, ceiling_usd: null, spent_usd: 0.58 } }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/projects/f1')) return ok(plain)
      if (url.endsWith('/spend?project=f1')) return ok({ project: { spent_usd: 0.58, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.58, ceiling_usd: 100, label: 'October' }, binding: 'month' })
      throw new Error(`unexpected ${url}`)
    }))
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('project-spend')).toHaveTextContent('$0.58 spent in this project · $0.58 of your $100 in October'))
    expect(screen.queryByRole('meter', { name: /project ceiling/ })).toBeNull()
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('accepts Voltage’s suggestion into the brief, and saves an edited brief after typing stops', async () => {
    const calls: { url: string; method: string; body?: unknown }[] = []
    vi.stubGlobal('fetch', routeFetch(calls))
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    const suggestion = await screen.findByTestId('suggestion')
    expect(suggestion).toHaveTextContent('“The offer ends 2 November.” It came up in bhaji-cam-ad.mp4 and applies to every video.')
    await userEvent.click(within(suggestion).getByRole('button', { name: 'Add to brief' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Project brief' })).toHaveValue('Brand is Bhaji Cam, said BAH-jee cam. The offer ends 2 November.'))
    expect(screen.queryByTestId('suggestion')).toBeNull()
    await userEvent.type(screen.getByRole('textbox', { name: 'Project brief' }), ' Warm, never pushy.')
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && (c.body as { brief?: string }).brief?.endsWith('Warm, never pushy.'))).toBe(true), { timeout: 2000 })
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
  })

  it('deletes the project only after the choice about its videos, then goes Home', async () => {
    const calls: { url: string; method: string }[] = []
    vi.stubGlobal('fetch', routeFetch(calls))
    const onDeleted = vi.fn()
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} onDeleted={onDeleted} />)
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'More for this project' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete project…' }))
    const ask = screen.getByTestId('delete-project')
    expect(ask).toHaveTextContent('Its 2 videos can go with it, or stay as standalone videos.')
    await userEvent.click(within(ask).getByRole('button', { name: 'Delete, keep the videos' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/projects/f1?videos=keep', method: 'DELETE' }))
    expect(onDeleted).toHaveBeenCalled()
    expect(window.location.hash).toBe('#home')
  })

  it('says when the project is gone', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'project not found' }, 404)))
    render(<ProjectPage me={ME} projectId="f9" onUpload={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('That project is gone.')
    expect(screen.getByRole('link', { name: '← Home' })).toHaveAttribute('href', '#home')
  })
})


describe('ProjectPage: the shared voice row (bug 2)', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('shows name · kind · Consent date, never 1970, and the name keeps its width', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const { container } = render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    const rows = await screen.findAllByTestId('shared-voice')
    expect(rows[0]).toHaveTextContent('Diwali Narrator')
    expect(rows[0]).toHaveTextContent('Designed · No consent needed · 2 videos')
    expect(rows[1]).toHaveTextContent('Deewar song')
    expect(rows[1]).toHaveTextContent(/Recorded · Consent 19 Oct 2026 · 1 video/)
    expect(rows[2]).toHaveTextContent('Recorded · Consent not recorded')
    // The name has its own line: it is a block of its own, not a flex item beside the tags.
    expect(within(rows[1]).getByText('Deewar song').parentElement).toHaveClass('min-w-0', 'flex-col')
    expect(container.textContent).not.toMatch(/1970/)
  })

  it('shows a legacy boolean consent as not recorded, not as 1 Jan 1970', async () => {
    const legacy = { ...DETAIL, voices: [{ voice_id: 'v9', name: 'Old', kind: 'recorded', seconds: 15, at: '2026-10-19T16:10:24.983Z', consent: true, consent_granted_at: undefined }] }
    vi.stubGlobal('fetch', vi.fn(async () => ok(legacy)))
    const { container } = render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    expect(await screen.findByTestId('shared-voice')).toHaveTextContent('Recorded · Consent not recorded')
    expect(container.textContent).not.toMatch(/1970/)
  })
})
