import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeSearch } from './HomeSearch'
import { hitHref } from '../lib/home'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

const RESULT = (q: string) => ({ query: q, total: 3, groups: [
  { project_id: 'f1', project_name: 'Diwali 2026', archived: true, hits: [
    { kind: 'brief', text: 'Say the Diwali price clearly.' },
    { kind: 'transcript', video_id: 'p2', filename: 'bhaji-cam-ad.mp4', at: 12.4, text: 'get the Diwali offer today', match: 'Diwali' },
  ] },
  { project_id: null, project_name: 'Standalone videos', archived: false, hits: [{ kind: 'video', video_id: 'p7', filename: 'diwali-teaser.mp4', text: 'diwali-teaser.mp4' }] },
] })

describe('D4: Home search', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('groups hits by project; a spoken word opens the editor at its time', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { calls.push(url); const q = new URL(url, 'http://x').searchParams.get('q') ?? ''; return ok(RESULT(q)) }))
    render(<HomeSearch debounceMs={0} />)
    await userEvent.type(screen.getByRole('searchbox'), 'Diwali')
    const group = await screen.findByTestId('search-group-f1')
    expect(within(group).getByText('Archived')).toBeInTheDocument()
    const said = within(group).getAllByTestId('search-hit')[1]
    expect(said).toHaveTextContent('Said · 0:12')
    expect(said).toHaveAttribute('href', '#v/p2@12.4')
    expect(within(said).getByText('Diwali', { selector: 'mark' })).toBeInTheDocument()
    expect(screen.getByTestId('search-group-none')).toHaveTextContent('diwali-teaser.mp4')
    expect(calls.at(-1)).toContain('/search?q=Diwali')
  })

  it('/ focuses the search unless you are typing; Escape clears it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ query: 'zz', total: 0, groups: [] })))
    render(<><textarea aria-label="Elsewhere" /><HomeSearch debounceMs={0} /></>)
    const other = screen.getByLabelText('Elsewhere')
    other.focus()
    fireEvent.keyDown(other, { key: '/' })
    expect(other).toHaveFocus()
    other.blur()
    fireEvent.keyDown(window, { key: '/' })
    expect(screen.getByRole('searchbox')).toHaveFocus()
    await userEvent.type(screen.getByRole('searchbox'), 'zz')
    expect(await screen.findByText(/Nothing matches/)).toHaveTextContent('Try a word someone says in a video')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('searchbox')).toHaveValue('')
  })

  it('says when search fails, with Try again', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'The server is down.' }, 500)))
    render(<HomeSearch debounceMs={0} />)
    await userEvent.type(screen.getByRole('searchbox'), 'offer')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server is down.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('links a project or brief hit to the project', () => {
    expect(hitHref({ kind: 'brief', text: 'x' }, 'f1')).toBe('#p/f1')
    expect(hitHref({ kind: 'video', video_id: 'p3', text: 'x' }, null)).toBe('#v/p3')
  })
})
