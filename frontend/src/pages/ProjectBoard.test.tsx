import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ProjectBoard } from './ProjectBoard'
import { ProjectFeed } from './ProjectFeed'
import { BatchPanel } from './BatchPanel'
import { feedItems, sentence } from './feedWords'
import { resetFlags } from '../flags/useFlags'
import type { ProjectEvent, ProjectSummary, Stage } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const video = (n: number, stage = 'draft', more: Partial<ProjectSummary> = {}) => ({ video_id: `p${n}`, project_id: 'f1', filename: `ad${n}.mp4`, duration: 12, created_at: '2026-10-20T00:00:00Z', edits: 0, stage, ...more }) as ProjectSummary
let id = 100
const ev = (verb: string, more: Partial<ProjectEvent> = {}): ProjectEvent => ({
  id: id--, project_id: 'f1', video_id: 'p1', actor_kind: 'user', actor_name: 'local', verb, target: '', payload: {}, at: '2026-10-21T00:00:00Z', you: true, ...more })
const names: Record<string, string> = { p1: 'bhaji-cam-ad.mp4', p2: 'reels-cut.mp4', p3: 'promo.mov' }
const nameOf = (v: string | null) => (v ? names[v] ?? null : null)

describe('C1: the feed in sentences', () => {
  it('says who did what, per verb', () => {
    expect(sentence([ev('stage.moved', { actor_kind: 'reviewer', actor_name: 'Priya', you: false, payload: { from: 'in_review', to: 'approved', why: 'Approved v5 by review link.' } })], nameOf)).toBe('Priya approved bhaji-cam-ad v5')
    expect(sentence([ev('stage.moved', { video_id: 'p3', payload: { from: 'draft', to: 'approved', why: '' } })], nameOf)).toBe('You moved promo to Approved')
    expect(sentence([ev('stage.moved', { actor_kind: 'voltage', actor_name: 'Voltage', you: false, payload: { from: 'approved', to: 'draft', why: 'A new edit was added after approval.' } })], nameOf))
      .toBe('bhaji-cam-ad went back to Draft: a new edit was added after it was approved')
    expect(sentence([ev('stage.moved', { payload: { from: 'draft', to: 'in_review', why: 'Review link sent to Priya.' } })], nameOf)).toBe('You sent bhaji-cam-ad for review to Priya')
    expect(sentence([ev('brief.saved', { payload: { version: 4 } })], nameOf)).toBe('You saved the brief as v4')
    expect(sentence([ev('video.deleted', { video_id: 'p9' })], nameOf)).toBe('You deleted a video')
  })

  it('folds a run of lines one actor added to one video into one item', () => {
    const voltage = { actor_kind: 'voltage' as const, actor_name: 'Voltage', you: false, video_id: 'p2' }
    const items = feedItems([ev('edit.shipped', voltage), ev('edit.shipped', voltage), ev('edit.shipped', voltage), ev('edit.shipped', voltage),
      ev('edit.shipped'), ev('edit.undone')], nameOf)
    expect(items.map((i) => i.text)).toEqual(['Voltage voiced 4 lines in reels-cut', 'You added 1 line to bhaji-cam-ad', 'You took 1 line out of bhaji-cam-ad'])
  })
})

/** The board with the page's list behind it, as ProjectPage keeps it. */
function Board({ videos }: { videos: ProjectSummary[] }) {
  const [list, setList] = useState(videos)
  return <ProjectBoard videos={list} briefChips syncChips onMoved={(vid: string, stage: Stage) => setList((l) => l.map((v) => (v.video_id === vid ? { ...v, stage } : v)))} />
}

describe('C1: the board', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows a column per stage with each card, its length, comments and chips', () => {
    render(<Board videos={[video(1, 'approved', { brief_changed: true }), video(2, 'in_review', { out_of_sync: true, open_comments: 2 }), video(3)]} />)
    expect(screen.getAllByRole('region').map((c) => c.getAttribute('aria-label'))).toEqual(['Draft, 1 video', 'In review, 1 video', 'Changes asked, 0 videos', 'Approved, 1 video', 'Exported, 0 videos'])
    const approved = within(screen.getByTestId('column-approved'))
    expect(approved.getByText('ad1.mp4')).toBeInTheDocument()
    expect(approved.getByText('0:12')).toBeInTheDocument()
    expect(approved.getByTestId('brief-changed')).toHaveTextContent('Brief changed')
    expect(within(screen.getByTestId('column-in_review')).getByTestId('open-comments')).toHaveTextContent('2 open comments')
    expect(within(screen.getByTestId('column-in_review')).getByTestId('board-out-of-sync')).toHaveTextContent('Out of sync')
  })

  it('a drag to another column writes one move; a drop where it was writes none', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { calls.push(`${init?.method} ${url} ${init?.body}`); return ok({ video_id: 'p1', stage: 'approved', label: 'Approved', moved: true }) }))
    render(<Board videos={[video(1), video(2)]} />)
    const card = within(screen.getByTestId('column-draft')).getAllByTestId('board-card')[0]
    const data = new Map<string, string>()
    const dataTransfer = { setData: (k: string, v: string) => data.set(k, v), getData: (k: string) => data.get(k) ?? '', types: ['application/x-voltage-video'], effectAllowed: '', dropEffect: '' }
    fireEvent.dragStart(card, { dataTransfer })
    fireEvent.dragOver(screen.getByTestId('column-approved'), { dataTransfer })
    fireEvent.drop(screen.getByTestId('column-approved'), { dataTransfer })
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatch(/^POST .*\/videos\/p1\/stage \{"to":"approved"\}$/)
    expect(within(screen.getByTestId('column-approved')).getByText('ad1.mp4')).toBeInTheDocument()
    expect(await screen.findByText('Moved ad1.mp4 to Approved.')).toBeInTheDocument()
    const again = within(screen.getByTestId('column-approved')).getByTestId('board-card')
    fireEvent.dragStart(again, { dataTransfer })
    fireEvent.drop(screen.getByTestId('column-approved'), { dataTransfer })
    await new Promise((r) => setTimeout(r, 20))
    expect(calls).toHaveLength(1)
  })

  it('Move to moves a card from the keyboard, and a refused move goes back', async () => {
    let refuse = false
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method} ${url} ${init?.body}`)
      return refuse ? ok({ detail: 'A stage is one of: Draft.' }, 422) : ok({ video_id: 'p1', stage: 'changes_asked', label: 'Changes asked', moved: true })
    }))
    render(<Board videos={[video(1, 'in_review')]} />)
    screen.getByRole('button', { name: 'Move ad1.mp4 to another stage' }).focus()
    await userEvent.keyboard('{Enter}')
    const menu = screen.getByRole('menu', { name: 'Move ad1.mp4 to' })
    expect(within(menu).getAllByRole('menuitem').map((b) => b.textContent)).toEqual(['Draft', 'Changes asked', 'Approved', 'Exported'])
    expect(within(menu).getByRole('menuitem', { name: 'Draft' })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => expect(calls).toEqual([expect.stringMatching(/\/videos\/p1\/stage \{"to":"changes_asked"\}$/)]))
    expect(within(screen.getByTestId('column-changes_asked')).getByText('ad1.mp4')).toBeInTheDocument()
    refuse = true
    await userEvent.click(screen.getByRole('button', { name: 'Move ad1.mp4 to another stage' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Exported' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not move ad1.mp4.')
    expect(within(screen.getByTestId('column-changes_asked')).getByText('ad1.mp4')).toBeInTheDocument()
  })
})

describe('C1: the Activity panel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads the feed, shows older on ask, and says when there is nothing yet', async () => {
    const pages: Record<string, unknown> = {
      first: { events: [ev('stage.moved', { id: 9, payload: { to: 'approved', why: '' } })], next: 9 },
      older: { events: [ev('brief.saved', { id: 5, payload: { version: 2 } })], next: null },
    }
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { urls.push(url); return ok(url.includes('before=9') ? pages.older : pages.first) }))
    render(<ProjectFeed projectId="f1" nameOf={nameOf} pollMs={60_000} />)
    expect(screen.getByText('Reading the activity…')).toBeInTheDocument()
    expect(await screen.findByText('You moved bhaji-cam-ad to Approved')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show older' }))
    expect(await screen.findByText('You saved the brief as v2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show older' })).not.toBeInTheDocument()
    expect(urls[0]).toMatch(/\/projects\/f1\/events\?limit=30$/)
  })

  it('shows an empty line, and an error with Try again', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => (fail ? ok({ detail: 'Server is down.' }, 500) : ok({ events: [], next: null }))))
    render(<ProjectFeed projectId="f1" nameOf={nameOf} pollMs={60_000} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server is down.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/Nothing has happened here yet/)).toBeInTheDocument()
  })
})

describe('C1: adding to an Approved video warns first', () => {
  beforeEach(() => resetFlags())
  afterEach(() => vi.unstubAllGlobals())

  it('Add all that passed on an Approved video shows the warning; nothing is added until Add anyway', async () => {
    const rows = [1, 2].map((n) => ({ video_id: `p${n}`, filename: `ad${n}.mp4`, stage: 'draft', stage_label: 'Draft', lines: 2, est_usd: 0.08, cap_usd: 0.5, job_id: `J${n}`,
      why: null, question: null, ready: 2, spent_usd: 0, added: null, answers: [], state: 'ready', label: 'Ready to review' }))
    const done = { batch_id: 'J9', project_id: 'f1', source: 'ask', goal: 'Make it 30% off', phase: 'finished', status: 'done', step: '2 of 2 videos finished', created_at: '2026-10-21T00:00:00Z',
      started_at: '2026-10-21T00:00:01Z', finished_at: null, totals: { videos: 2, lines: 4, est_usd: 0.2, est_s: null, cap_usd: 1 }, summary: null, rows, counts: {}, spent_usd: 0.12, can_add: true }
    const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch', 'projects.review'] })
      if (url.endsWith('/me/onboarding')) return ok({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-batch'], checklist: [], checklist_hidden: true })
      if (init?.method === 'POST') { posts.push(`${url} ${init.body ?? ''}`); return ok(done) }
      return ok({ batches: [done] })
    }))
    const added = vi.fn()
    render(<BatchPanel projectId="f1" videos={[video(1, 'approved'), video(2)]} onAdded={added} />)
    const add = await screen.findByRole('button', { name: /Add all that passed/ })
    await waitFor(() => expect(add).toBeEnabled())
    await new Promise((r) => setTimeout(r, 10))   // the flags arrive
    await userEvent.click(add)
    const warning = await screen.findByTestId('stage-warning')
    expect(warning).toHaveTextContent('This video is Approved. Adding this moves it back to Draft.')
    expect(posts).toEqual([])
    await userEvent.click(within(warning).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByTestId('stage-warning')).not.toBeInTheDocument()
    expect(posts).toEqual([])
    await userEvent.click(screen.getByRole('button', { name: /Add all that passed/ }))
    await userEvent.click(within(await screen.findByTestId('stage-warning')).getByRole('button', { name: 'Add anyway' }))
    await waitFor(() => expect(posts).toEqual([expect.stringMatching(/\/batches\/J9\/add-all \{"confirm_stage":true\}$/)]))
    expect(added).toHaveBeenCalled()
  })
})
