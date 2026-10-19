import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoicesPage } from './VoicesPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ashish@example.com', name: 'Ashish Sinha', picture: null } }
const MINE = [
  { voice_id: 'v1', name: 'Ashish', seconds: 42, at: '2026-10-10T10:00:00Z', kind: 'recorded', sample_sha: 'a'.repeat(64), used_in: 1 },
  { voice_id: 'v2', name: 'Goa Narrator', seconds: 0, at: '2026-10-11T10:00:00Z', kind: 'designed', description: 'An Indian woman near fifty, soft and slightly husky', sample_sha: 'b'.repeat(64) },
]
const CATALOGUE = [
  { voice_id: 'c1', name: 'Sarah', description: '', gender: 'female', accent: 'american', age: null, preview_url: 'https://cdn.example/sarah.mp3' },
  { voice_id: 'c2', name: 'Brian', description: '', gender: 'male', accent: 'american', age: null, preview_url: null },
  { voice_id: 'v1', name: 'Ashish', description: '', gender: null, accent: null, age: null, category: 'mine' },
]
const MADE = [
  { voice_id: 'm1', name: 'Diwali Narrator', kind: 'designed', project_id: 'p2', filename: 'bhaji-cam-ad.mp4', description: 'Warm, unhurried Indian woman near fifty' },
  { voice_id: 'm2', name: 'The Customer', kind: 'cloned', project_id: 'p2', filename: 'bhaji-cam-ad.mp4', kept: true },
]
const SPEAKERS = [{ video_id: 'p2', filename: 'bhaji-cam-ad.mp4', label: 'speaker-2', name: 'The Customer', seconds: 14.2 }]
const PREVIEWS = [1, 2, 3].map((n) => ({ generated_voice_id: `g${n}`, sha256: String(n).repeat(64), duration: 4.2, text: 'A sample line.' }))

type Call = { url: string; method: string; body: Record<string, unknown> | undefined }
/** Routes by URL and records every write. */
function routeFetch() {
  const calls: Call[] = []
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (method !== 'GET') calls.push({ url, method, body })
    if (url.endsWith('/voices') && method === 'GET') return ok({ default: 'c1', voices: CATALOGUE, mine: MINE, slots: { used: 14, limit: 30 } })
    if (url.endsWith('/voices/made')) return ok({ voices: MADE })
    if (url.endsWith('/voices/speakers')) return ok({ speakers: SPEAKERS })
    if (url.endsWith('/voices/mine/keep')) return ok({ voice_id: 'm1', name: 'Diwali Narrator', seconds: 0, at: '2026-10-18T10:00:00Z', kind: 'designed' })
    if (url.endsWith('/voices/design')) return ok({ previews: PREVIEWS })
    if (url.endsWith('/voices/mine/from-preview')) return ok({ voice_id: 'v9', name: body.name, seconds: 0, at: '2026-10-18T10:00:00Z', kind: 'designed' })
    if (url.endsWith('/voices/mine/from-speaker')) return ok({ voice_id: 'v8', name: body.name, seconds: 14, at: '2026-10-18T10:00:00Z', kind: 'cloned' })
    if (url.endsWith('/voices/mine') && method === 'POST') return ok({ voice_id: 'v7', name: 'Ashish', seconds: 12, at: '2026-10-18T10:00:00Z', kind: 'recorded' })
    if (/\/voices\/mine\/v\d+$/.test(url) && method === 'DELETE') return ok({})
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', f)
  return calls
}
const consent = () => screen.getByRole('checkbox', { name: /I have the right to use this voice/ })

describe('VoicesPage', () => {
  beforeEach(() => {
    // jsdom has no media playback; the page only needs play/pause to exist.
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('shows yours, the project voices and the catalogue with counts, and filters by tab', async () => {
    routeFetch()
    render(<VoicesPage me={ME} />)
    expect(await screen.findByRole('heading', { name: 'Yours' })).toBeInTheDocument()
    expect(screen.getByText(/Voice slots/)).toHaveTextContent('Voice slots 14 / 30')
    expect(screen.getByRole('tab', { name: 'Yours · 2' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'In projects · 2' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Catalogue · 2' })).toBeInTheDocument()   // the voice of yours is not listed twice
    const yours = within(screen.getByRole('heading', { name: 'Yours' }).closest('section')!)
    expect(yours.getByText('Recorded')).toBeInTheDocument()
    expect(yours.getByText('Designed')).toBeInTheDocument()
    expect(screen.getByText('Your own voice, from a 42 s recording')).toBeInTheDocument()
    expect(screen.getByText('Used in 1 project')).toBeInTheDocument()
    expect(screen.getByText(/^Saved · 11 Oct/)).toBeInTheDocument()
    expect(screen.getByText('Diwali Narrator')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '✓ Kept in yours' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Hear Sarah' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hear Brian' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Catalogue · 2' }))
    expect(screen.getByRole('tab', { name: 'Catalogue · 2' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('heading', { name: 'Yours' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Catalogue' })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'In projects · 2' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'Made inside a project' })).toBeInTheDocument()
  })

  it('keeps a project voice in yours', async () => {
    const calls = routeFetch()
    render(<VoicesPage me={ME} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Keep in my voices' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/voices/mine/keep', method: 'POST', body: { voice_id: 'm1' } }))
    expect(await screen.findAllByRole('button', { name: '✓ Kept in yours' })).toHaveLength(2)
    expect(screen.getByRole('tab', { name: 'Yours · 3' })).toBeInTheDocument()
    expect(screen.getByText(/Voice slots/)).toHaveTextContent('15 / 30')
  })

  it('keeps the CTA shut until the inputs are filled and the consent is ticked', async () => {
    routeFetch()
    render(<VoicesPage me={ME} />)
    await screen.findByRole('heading', { name: 'Yours' })
    expect(screen.getByRole('radio', { name: /Record or upload/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: 'Clone and keep' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Start recording' })).toBeDisabled()   // no MediaRecorder in jsdom
    await userEvent.click(screen.getByRole('radio', { name: /Describe it/ }))
    const cta = screen.getByRole('button', { name: 'Design 3 previews' })
    expect(cta).toBeDisabled()
    expect(screen.getByText('~$0.06 · 1 slot')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Describe the voice'), 'A calm British man')
    expect(cta).toBeDisabled()
    await userEvent.click(consent())
    expect(cta).toBeEnabled()
    await userEvent.clear(screen.getByLabelText('Describe the voice'))
    expect(cta).toBeDisabled()
  })

  it('designs three previews, lets you pick one, and keeps it under a name', async () => {
    const calls = routeFetch()
    render(<VoicesPage me={ME} />)
    await screen.findByRole('heading', { name: 'Yours' })
    await userEvent.click(screen.getByRole('radio', { name: /Describe it/ }))
    await userEvent.type(screen.getByLabelText('Describe the voice'), 'A calm British man')
    await userEvent.type(screen.getByLabelText('Name'), 'Explainer')
    await userEvent.click(consent())
    await userEvent.click(screen.getByRole('button', { name: 'Design 3 previews' }))
    expect(await screen.findByText('Preview 1')).toBeInTheDocument()
    expect(calls).toContainEqual({ url: '/api/voices/design', method: 'POST', body: { description: 'A calm British man' } })
    const keep = screen.getByRole('button', { name: 'Keep as Explainer' })
    expect(keep).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Hear preview 1' }))
    expect(screen.getByRole('button', { name: 'Stop preview 1' })).toHaveAttribute('aria-pressed', 'true')
    const uses = screen.getAllByRole('radio', { name: 'Use this' })
    expect(uses).toHaveLength(3)
    await userEvent.click(uses[0])
    expect(screen.getByRole('radio', { name: '✓ Using' })).toHaveAttribute('aria-checked', 'true')
    expect(keep).toBeEnabled()
    await userEvent.click(keep)
    await waitFor(() => expect(calls).toContainEqual({
      url: '/api/voices/mine/from-preview', method: 'POST',
      body: { generated_voice_id: 'g1', name: 'Explainer', sha256: '1'.repeat(64), description: 'A calm British man', consent: true },
    }))
    expect(await screen.findByText('Kept Explainer in your voices.')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Yours · 3' })).toBeInTheDocument()
  })

  it('clones a project speaker and keeps it', async () => {
    const calls = routeFetch()
    render(<VoicesPage me={ME} />)
    await screen.findByRole('heading', { name: 'Yours' })
    await userEvent.click(screen.getByRole('radio', { name: /From a project speaker/ }))
    expect(screen.getByRole('option', { name: 'The Customer · bhaji-cam-ad · 14 s' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('The Customer')
    await userEvent.click(consent())
    await userEvent.click(screen.getByRole('button', { name: 'Clone and keep' }))
    await waitFor(() => expect(calls).toContainEqual({
      url: '/api/voices/mine/from-speaker', method: 'POST', body: { video_id: 'p2', label: 'speaker-2', name: 'The Customer', consent: true },
    }))
    expect(await screen.findByText('Kept The Customer in your voices.')).toBeInTheDocument()
  })

  it('uploads a recording file under your name', async () => {
    const calls = routeFetch()
    render(<VoicesPage me={ME} />)
    await screen.findByRole('heading', { name: 'Yours' })
    expect(screen.getByLabelText('Name')).toHaveValue('Ashish')
    await userEvent.upload(screen.getByLabelText('Choose a recording'), new File(['bytes'], 'me.m4a', { type: 'audio/mp4' }))
    expect(screen.getByText('me.m4a')).toBeInTheDocument()
    await userEvent.click(consent())
    await userEvent.click(screen.getByRole('button', { name: 'Clone and keep' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/voices/mine' && c.method === 'POST')).toBe(true))
    expect(await screen.findByText('Kept Ashish in your voices.')).toBeInTheDocument()
  })

  it('hears a voice of yours, and removes one only after a confirm', async () => {
    const calls = routeFetch()
    render(<VoicesPage me={ME} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Hear Ashish' }))
    expect(screen.getByRole('button', { name: 'Stop Ashish' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'More for Ashish' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Remove…' }))
    const confirm = screen.getByRole('group', { name: 'Remove Ashish?' })
    expect(calls).toEqual([])
    await userEvent.click(within(confirm).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/voices/mine/v1', method: 'DELETE', body: undefined }))
    await waitFor(() => expect(screen.queryByText('Your own voice, from a 42 s recording')).not.toBeInTheDocument())
    expect(screen.getByText(/Voice slots/)).toHaveTextContent('13 / 30')
  })
})
