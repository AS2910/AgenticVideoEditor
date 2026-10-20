import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BinPage } from './BinPage'
import { Shell } from './Shell'
import { resetFlags } from '../flags/useFlags'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
const AGO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

const ITEMS = [
  { kind: 'video', id: 'p4', name: 'reels-cut.mp4', deleted_at: AGO(1), deleted_by: 'local', deleted_by_you: true, days_left: 29, project_id: 'f1', project_name: 'Diwali 2026', project_in_bin: false, with_project: false },
  { kind: 'project', id: 'f2', name: 'Spring sale', deleted_at: AGO(2), deleted_by: 'local', deleted_by_you: true, days_left: 28, project_id: null, project_name: null, videos: 1 },
  { kind: 'video', id: 'p5', name: 'spring.mp4', deleted_at: AGO(2), deleted_by: 'local', deleted_by_you: true, days_left: 28, project_id: 'f2', project_name: 'Spring sale', project_in_bin: true, with_project: true },
  { kind: 'voice', id: 'V1', name: 'Ashish warm', deleted_at: AGO(28), deleted_by: 'local', deleted_by_you: true, days_left: 2, project_id: null, project_name: null, consent: true },
]

function routeFetch(calls: string[], opts: { fail?: boolean; items?: unknown[] } = {}) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(`${method} ${url}`)
    if (url.endsWith('/me/flags')) return ok({ flags: ['projects.reuse'] })
    if (url.endsWith('/bin') && method === 'GET') return opts.fail ? ok({ detail: 'The server is down.' }, 500) : ok({ items: opts.items ?? ITEMS, days: 30 })
    if (url.endsWith('/bin/project/f2/restore')) return ok({ kind: 'project', id: 'f2', videos: ['p5'] })
    if (url.endsWith('/bin/video/p4/restore')) return ok({ kind: 'video', id: 'p4', project_id: 'f1', project_name: 'Diwali 2026', standalone_because: null })
    if (url.endsWith('/bin/voice/V1/restore')) return ok({ detail: 'That is not in the Bin any more.' }, 404)
    throw new Error(`unexpected ${method} ${url}`)
  })
}

describe('D3: the Bin', () => {
  beforeEach(() => { resetFlags() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('lists each item with who deleted it, where it goes back and the days left', async () => {
    vi.stubGlobal('fetch', routeFetch([]))
    render(<BinPage me={ME} />)
    const video = await screen.findByTestId('bin-video:p4')
    expect(video).toHaveTextContent('Deleted by you yesterday')
    expect(video).toHaveTextContent('Goes back to Diwali 2026')
    expect(video).toHaveTextContent('29 days left')
    expect(screen.getByTestId('bin-project:f2')).toHaveTextContent('1 video comes back with it')
    expect(screen.getByTestId('bin-video:p5')).toHaveTextContent('Deleted with Spring sale')
    const voice = screen.getByTestId('bin-voice:V1')
    expect(voice).toHaveTextContent('consent record is kept')
    expect(within(voice).getByText('2 days left')).toHaveClass('need')
    await userEvent.click(screen.getByRole('tab', { name: /Voices · 1/ }))
    expect(screen.queryByTestId('bin-video:p4')).toBeNull()
  })

  it('restores a project with its videos and says where things went; the action is last', async () => {
    const calls: string[] = []
    const onRestored = vi.fn()
    vi.stubGlobal('fetch', routeFetch(calls))
    render(<BinPage me={ME} onRestored={onRestored} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restore Spring sale' }))
    await waitFor(() => expect(screen.getByTestId('bin-toast')).toHaveTextContent('Restored Spring sale with 1 video.'))
    expect(screen.queryByTestId('bin-project:f2')).toBeNull()
    expect(screen.queryByTestId('bin-video:p5')).toBeNull()
    expect(onRestored).toHaveBeenCalledWith('project', 'f2')
    expect(calls).toContain('POST /api/bin/project/f2/restore')
    await userEvent.click(screen.getByRole('button', { name: 'Restore reels-cut.mp4' }))
    await waitFor(() => expect(screen.getByTestId('bin-toast')).toHaveTextContent('Restored reels-cut.mp4 to Diwali 2026.'))
    expect(within(screen.getByTestId('bin-toast')).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '#v/p4')
  })

  it('shows a failed restore on its row and keeps the item', async () => {
    vi.stubGlobal('fetch', routeFetch([]))
    render(<BinPage me={ME} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restore Ashish warm' }))
    expect(await within(screen.getByTestId('bin-voice:V1')).findByRole('alert')).toHaveTextContent('That is not in the Bin any more.')
  })

  it('has empty, loading and error states', async () => {
    vi.stubGlobal('fetch', routeFetch([], { items: [] }))
    const { unmount } = render(<BinPage me={ME} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the Bin')
    expect(await screen.findByTestId('bin-empty')).toHaveTextContent('The Bin is empty.')
    unmount()
    vi.stubGlobal('fetch', routeFetch([], { fail: true }))
    render(<BinPage me={ME} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The server is down.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('puts Bin in the main nav only with the flag on', async () => {
    vi.stubGlobal('fetch', routeFetch([]))
    render(<Shell active="projects" me={ME}><p>x</p></Shell>)
    expect(await screen.findByRole('link', { name: 'Bin' })).toHaveAttribute('href', '#bin')
  })
})
