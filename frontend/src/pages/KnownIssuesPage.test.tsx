import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { KnownIssuesPage } from './KnownIssuesPage'
import { parseRoute, hrefFor } from '../lib/route'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ann@example.com', name: 'Ann', picture: null } }
const PAGE = {
  title: 'Known issues', updated: '2026-10-24', summary: 'Voltage is in beta.',
  sections: [{ heading: 'Voices', body: '- **Cloning a voice is closed for now.** Describe a voice instead.' }, { heading: 'Money', body: '- Receipts are not emailed yet.' }],
}

describe('KnownIssuesPage', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('reads the file through the help API and draws one section per heading', async () => {
    const f = vi.fn(async (url: string) => (url.endsWith('/help/known-issues') ? ok(PAGE) : Promise.reject(new Error(url))))
    vi.stubGlobal('fetch', f)
    render(<KnownIssuesPage me={ME} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Known issues')
    expect(await screen.findByRole('heading', { level: 2, name: 'Voices' })).toBeInTheDocument()
    expect(screen.getAllByTestId('known-issue-section')).toHaveLength(2)
    expect(screen.getByText('Cloning a voice is closed for now.').tagName).toBe('STRONG')
    expect(screen.getByText('Voltage is in beta.')).toBeInTheDocument()
    expect(f).toHaveBeenCalledWith('/api/help/known-issues')
  })

  it('has the Beta badge in the header, linking here, and its own route', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(PAGE)))
    render(<KnownIssuesPage me={ME} />)
    const badge = screen.getByRole('link', { name: 'Beta: see the known issues' })
    expect(badge).toHaveAttribute('href', '#known-issues')
    expect(parseRoute('#known-issues')).toEqual({ page: 'knownIssues' })
    expect(hrefFor({ page: 'knownIssues' })).toBe('#known-issues')
  })

  it('says so when the page cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: 'down' }), text: async () => '' }) as Response))
    render(<KnownIssuesPage me={ME} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/down|could not be read/)
  })
})
