import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExportPage } from './ExportPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 48.9, container: 'mp4' }
const PROJECT = { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', duration: 48.9, media: MEDIA, consent: null, transcript: [], edits: [], messages: [] }
const RENDER = { sha256: 'r'.repeat(64), duration: 48.9, filename: 'bhaji-cam-ad-edited.mp4' }
const RECEIPT = {
  turns: 4, takes: 6, spent_usd: 1.07, drafts: 0, render: RENDER,
  changes: [
    { edit_id: 'e1', start: 4.9, text: 'Start a Bhaji Cam session.', kind: 'changed', note: "Customer's own voice · picture 1.12× for 1.5 s" },
    { edit_id: 'e2', start: 8.4, text: 'Thirty off.', kind: 'added', note: 'over the picture' },
  ],
}
const ME = { mode: 'off' as const, user: null }

/** Routes by URL. With no render in the receipt, the first POST /export makes one. */
function routeFetch(receipt: typeof RECEIPT | (Omit<typeof RECEIPT, 'render'> & { render: null }) = RECEIPT) {
  const calls: string[] = []
  let current: unknown = receipt
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method !== 'GET') calls.push(`${method} ${url}`)
    if (url.endsWith('/videos/p2') && method === 'GET') return ok(PROJECT)
    if (url.endsWith('/videos/p2/receipt')) return ok(current)
    if (url.endsWith('/videos/p2/export') && method === 'POST') { current = { ...receipt, render: { ...RENDER, duration: 50.1 } }; return ok({ segments: [], render: MEDIA }) }
    if (url.endsWith('/videos/p2/variants') && method === 'POST') return ok({ ...PROJECT, video_id: 'p3' })
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', f)
  return calls
}

describe('ExportPage', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.location.hash = '' })

  it('shows the file, what went into it, and a download link', async () => {
    const calls = routeFetch()
    render(<ExportPage projectId="p2" me={ME} onBack={() => {}} />)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent("It's out.")
    expect(calls).toEqual([])   // nothing re-rendered: the receipt already had a file
    expect(screen.getByRole('status')).toHaveTextContent(/^Rendered$/)   // no seconds unless measured
    expect(screen.getByText('bhaji-cam-ad-edited.mp4 · 0:48.9, the same length as the original · H.264 + AAC · plays everywhere.')).toBeInTheDocument()
    const dl = screen.getByRole('link', { name: 'Download MP4' })
    expect(dl).toHaveAttribute('href', `/api/videos/p2/artifacts/${'r'.repeat(64)}`)
    expect(dl).toHaveAttribute('download', 'bhaji-cam-ad-edited.mp4')
    expect(screen.getByTestId('render')).toHaveAttribute('src', `/api/videos/p2/artifacts/${'r'.repeat(64)}`)
    expect(screen.getByText('2 changes')).toBeInTheDocument()
    expect(screen.getByText('0:04.9')).toBeInTheDocument()
    expect(screen.getByText('Start a Bhaji Cam session.')).toBeInTheDocument()
    expect(screen.getByText('Changed')).toBeInTheDocument()
    expect(screen.getByText('Added')).toBeInTheDocument()
    expect(screen.getByText('Still a draft, not in the file: nothing.')).toBeInTheDocument()
    expect(screen.getByText('Turns').nextElementSibling).toHaveTextContent('4')
    expect(screen.getByText('Takes').nextElementSibling).toHaveTextContent('6')
    expect(screen.getByText('Spent').nextElementSibling).toHaveTextContent('$1.07')
    expect(screen.getByRole('link', { name: 'Full receipt →' })).toHaveAttribute('href', '#usage')
    expect(screen.getByRole('link', { name: '← Back to editing' })).toHaveAttribute('href', '#v/p2')
    expect(screen.getByRole('link', { name: 'bhaji-cam-ad.mp4' })).toHaveAttribute('href', '#v/p2')
  })

  it('copies the absolute link and says so for a moment', async () => {
    routeFetch()
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<ExportPage projectId="p2" me={ME} onBack={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/api/videos/p2/artifacts/${'r'.repeat(64)}`)
    expect(screen.getByRole('button', { name: '✓ Link copied' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument(), { timeout: 3000 })
  })

  it('makes a variant and goes to it', async () => {
    const calls = routeFetch()
    render(<ExportPage projectId="p2" me={ME} onBack={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Make a variant' }))
    await waitFor(() => expect(window.location.hash).toBe('#v/p3'))
    expect(calls).toContain('POST /api/videos/p2/variants')
  })

  it('renders once when the project has no file yet, timing it', async () => {
    const calls = routeFetch({ ...RECEIPT, drafts: 2, render: null })
    render(<ExportPage projectId="p2" me={ME} onBack={() => {}} />)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent("It's out.")
    expect(calls.filter((c) => c === 'POST /api/videos/p2/export')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent(/^Rendered in \d+ s$/)
    // 50.1 s against a 48.9 s original: not the same length, so it does not say so.
    expect(screen.getByText('bhaji-cam-ad-edited.mp4 · 0:50.1 · H.264 + AAC · plays everywhere.')).toBeInTheDocument()
    expect(screen.getByText('Still a draft, not in the file: 2.')).toBeInTheDocument()
  })
})
