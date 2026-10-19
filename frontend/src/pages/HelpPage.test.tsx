import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HelpPage } from './HelpPage'
import type { HelpArticle } from '../types'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ashish@example.com', name: 'Ashish Sinha', picture: null } }
const ARTICLES: HelpArticle[] = [
  { slug: 'what-voltage-does', section: 'Getting started', title: 'What Voltage does', summary: 'Voltage changes what a video says without a reshoot.', body: 'It rewrites lines, voices them, and keeps the picture moving.', order: 1, tour: null },
  { slug: 'your-first-edit', section: 'Getting started', title: 'Your first edit', summary: 'Upload a clip, confirm who is speaking, then say the goal.', body: 'It proposes changes; you hear them and add the ones you want.\n\n- Hear it\n- Add it', order: 2, tour: 'goal' },
  { slug: 'undo-anything', section: 'Editing lines', title: 'Undo anything', summary: 'Every change can be taken out, even after export.', body: 'Export again to update the file.', order: 1, tour: null },
  { slug: 'the-spend-meter', section: 'Money and limits', title: 'The spend meter', summary: 'What this project has spent against its ceiling.', body: 'Click it for the breakdown.', order: 1, tour: null },
]
const handlers = () => ({ onReplay: vi.fn(), onAsk: vi.fn(), onShowMe: vi.fn() })

describe('HelpPage', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, '', '#help') })

  it('loads the articles, numbers the sections, and marks Help as the page', async () => {
    const f = vi.fn(async (url: string) => (url.endsWith('/help') ? ok({ articles: ARTICLES }) : Promise.reject(new Error(`unexpected ${url}`))))
    vi.stubGlobal('fetch', f)
    render(<HelpPage me={ME} {...handlers()} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('How can we help?')
    expect(screen.getByRole('status')).toHaveTextContent('Loading Help…')
    const grid = screen.getByLabelText('Help sections')
    await waitFor(() => expect(within(grid).getAllByRole('heading', { level: 2 })).toHaveLength(3))
    expect(within(grid).getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['01Getting started', '02Editing lines', '03Money and limits'])
    expect(within(grid).getAllByRole('button')).toHaveLength(4)
    expect(screen.getByText('4 articles')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '#home')
    expect(f).toHaveBeenCalledWith('/api/help')
  })

  it('says so when Help cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: 'down' }), text: async () => '' }) as Response))
    render(<HelpPage me={ME} {...handlers()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/down|could not be read/)
  })

  it('searches the words of title, summary, body and section, and says when nothing matches', async () => {
    render(<HelpPage me={ME} articles={ARTICLES} {...handlers()} />)
    const box = screen.getByRole('searchbox', { name: 'Search Help' })
    await userEvent.type(box, 'breakdown')
    const results = screen.getByLabelText('Search results')
    expect(within(results).getAllByRole('button')).toHaveLength(1)
    expect(results).toHaveTextContent('The spend meter')
    expect(results).toHaveTextContent('Money and limits →')
    expect(screen.getByText('1 found')).toBeInTheDocument()
    expect(screen.queryByLabelText('Help sections')).not.toBeInTheDocument()
    await userEvent.clear(box)
    await userEvent.type(box, 'editing')
    expect(within(screen.getByLabelText('Search results')).getAllByRole('button')).toHaveLength(1)
    await userEvent.clear(box)
    await userEvent.type(box, 'zzzz')
    expect(screen.getByLabelText('Search results')).toHaveTextContent('Nothing matches. Ask Voltage in any project')
    expect(screen.getByText('0 found')).toBeInTheDocument()
  })

  it('opens the reader from a hit, with Show me, Ask Voltage and a local thank-you', async () => {
    const h = handlers()
    render(<HelpPage me={ME} articles={ARTICLES} {...h} />)
    await userEvent.click(screen.getByRole('button', { name: /Your first edit/ }))
    const reader = screen.getByRole('dialog', { name: 'Your first edit' })
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Your first edit' })).toHaveFocus())
    expect(reader).toHaveTextContent('Getting started')
    expect(within(reader).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Hear it', 'Add it'])
    expect(window.location.hash).toBe('#help/your-first-edit')
    await userEvent.click(within(reader).getByRole('button', { name: /Show me/ }))
    expect(h.onShowMe).toHaveBeenCalledWith('goal')
    await userEvent.click(within(reader).getByRole('button', { name: 'Ask Voltage about this' }))
    expect(h.onAsk).toHaveBeenCalledOnce()
    await userEvent.click(within(reader).getByRole('button', { name: 'Yes' }))
    expect(within(reader).getByRole('status')).toHaveTextContent('Thanks')
    expect(within(reader).queryByRole('button', { name: 'No' })).not.toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(window.location.hash).toBe('#help')
  })

  it('opens on the article the address names, without a Show me when it has no tour', async () => {
    render(<HelpPage me={ME} articles={ARTICLES} initialSlug="undo-anything" {...handlers()} />)
    const reader = screen.getByRole('dialog', { name: 'Undo anything' })
    expect(within(reader).queryByRole('button', { name: /Show me/ })).not.toBeInTheDocument()
    await userEvent.click(within(reader).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('replays the tutorial, asks Voltage, and opens the keyboard sheet from the strip', async () => {
    const h = handlers()
    render(<HelpPage me={ME} articles={ARTICLES} {...h} />)
    await userEvent.click(screen.getByRole('button', { name: /Replay the tutorial/ }))
    expect(h.onReplay).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: /Replay the tutorial/ })).toHaveTextContent('3 min · sample ad · free')
    await userEvent.click(screen.getByRole('button', { name: /Ask Voltage/ }))
    expect(h.onAsk).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: 'Keyboard shortcuts' }))
    expect(await screen.findByRole('dialog', { name: 'Keyboard' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
