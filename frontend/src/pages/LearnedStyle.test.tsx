import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LearnedStyle } from './LearnedStyle'
import { DiscardWhy } from '../components/DiscardWhy'
import { DISCARD_REASONS } from '../lib/learned'
import type { LearnedItem, LearnedPage } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const item = (id: number, extra: Partial<LearnedItem> = {}): LearnedItem => ({
  item_id: id, project_id: 'f1', kind: 'rule', text: 'Keep lines under eight words.', why: 'You shortened 4 of the last 10 lines before adding them.',
  status: 'suggested', rule_id: null, brief_version: null, at_count: 10, created_at: '', decided_at: null, decided_by: null, ...extra,
})
const PAGE = (extra: Partial<LearnedPage> = {}): LearnedPage => ({ pending: null, learned: [], decisions: 4, every: 10, reasons: [...DISCARD_REASONS], ...extra })
const PROJECT = { project_id: 'f1', name: 'Diwali', brief: 'Warm.\nAlways name the sale.', ceiling_usd: null, spent_usd: 0, created_at: '', brief_version: 3 }

describe('D2: What Voltage has learned', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says how it learns when there is nothing yet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(PAGE())))
    render(<LearnedStyle projectId="f1" />)
    expect(await screen.findByTestId('learned-empty')).toHaveTextContent('Every 10 decisions on Voltage\'s lines')
    expect(screen.getByTestId('learned-empty')).toHaveTextContent('6 more to the next look.')
  })

  it('shows the suggestion with why, adds it only on Add, then lists it; Remove takes it out', async () => {
    const calls: string[] = []
    let state = PAGE({ pending: item(7, { kind: 'brief', text: 'Always name the sale.' }), decisions: 10 })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url.endsWith('/accept')) state = PAGE({ learned: [item(7, { kind: 'brief', text: 'Always name the sale.', status: 'accepted' })], decisions: 10, project: PROJECT })
      if (method === 'DELETE') state = PAGE({ decisions: 10, project: { ...PROJECT, brief: 'Warm.', brief_version: 4 } })
      return ok(state)
    }))
    const onProject = vi.fn()
    render(<LearnedStyle projectId="f1" onProject={onProject} />)
    const card = await screen.findByTestId('learned-suggestion')
    expect(card).toHaveTextContent('Voltage noticed · for the brief')
    expect(card).toHaveTextContent('Nothing changes until you add it.')
    expect(within(card).getAllByRole('button').map((b) => b.textContent)).toEqual(['Not now', 'Add to brief'])   // the next action last
    expect(calls).toEqual(['GET /api/projects/f1/learned'])
    await userEvent.click(within(card).getByRole('button', { name: 'Add to brief' }))
    expect(await screen.findByTestId('learned-item')).toHaveTextContent('Always name the sale.')
    expect(onProject).toHaveBeenCalledWith(PROJECT)
    await userEvent.click(screen.getByRole('button', { name: 'Remove Always name the sale.' }))
    await waitFor(() => expect(screen.queryByTestId('learned-item')).toBeNull())
    expect(screen.getByRole('status')).toHaveTextContent('Removed. The brief has a new version without it.')
    expect(calls).toContain('DELETE /api/projects/f1/learned/7')
  })

  it('shows a read error with Try again', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'Down.' }, 500)))
    render(<LearnedStyle projectId="f1" />)
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('D2: why a line was discarded', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends a picked reason, or closes on Skip without sending', async () => {
    const posts: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { posts.push([url, JSON.parse(String(init?.body))]); return ok({ decision_id: 5, reason: 'Too long' }) }))
    const onClose = vi.fn()
    const { unmount } = render(<DiscardWhy videoId="p1" decisionId={5} line="the line at 0:04" reasons={DISCARD_REASONS} onClose={onClose} />)
    expect(screen.getByTestId('discard-why')).toHaveTextContent('Discarded the line at 0:04. Tell Voltage why? Optional.')
    await userEvent.click(screen.getByRole('button', { name: 'Too long' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Thanks.')
    expect(posts).toEqual([['/api/videos/p1/decisions/5/reason', { reason: 'Too long' }]])
    unmount()
    render(<DiscardWhy videoId="p1" decisionId={6} line="the line at 0:09" reasons={DISCARD_REASONS} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(onClose).toHaveBeenCalled()
    expect(posts).toHaveLength(1)
  })
})
