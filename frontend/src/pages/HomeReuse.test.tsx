import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from './ProjectsPage'
import { ProjectPage } from './ProjectPage'
import { resetFlags } from '../flags/useFlags'
import { needsAttention, sortVideos } from '../lib/home'
import type { ProjectSummary } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
const v = (id: string, extra: Partial<ProjectSummary>): ProjectSummary => ({ video_id: id, filename: `${id}.mp4`, duration: 10, created_at: '2026-10-01T00:00:00.000Z', edits: 0, project_id: null, ...extra })
const VIDEOS = [
  v('b', { created_at: '2026-10-03T00:00:00.000Z', last_edited_at: '2026-10-04T00:00:00.000Z', stage: 'approved', project_id: 'f1', project_name: 'Diwali' }),
  v('a', { created_at: '2026-10-05T00:00:00.000Z', stage: 'draft', brief_changed: true, project_id: 'f1', project_name: 'Diwali' }),
  v('c', { created_at: '2026-10-02T00:00:00.000Z', last_edited_at: '2026-10-20T00:00:00.000Z', stage: 'in_review', open_comments: 1 }),
  v('z', { project_id: 'f9', project_name: 'Old', project_archived: true }),
]
const FOLDERS = [{ project_id: 'f1', name: 'Diwali', brief: '', ceiling_usd: null, spent_usd: 0, created_at: '2026-10-01T00:00:00.000Z', video_count: 2 }]

describe('D4: sorting and needs attention', () => {
  it('sorts by last edited, created, name and stage', () => {
    const ids = (by: Parameters<typeof sortVideos>[1]) => sortVideos(VIDEOS.slice(0, 3), by).map((x) => x.video_id)
    expect(ids('edited')).toEqual(['c', 'a', 'b'])
    expect(ids('created')).toEqual(['a', 'b', 'c'])
    expect(ids('name')).toEqual(['a', 'b', 'c'])
    expect(ids('stage')).toEqual(['a', 'c', 'b'])
    expect(VIDEOS.filter(needsAttention).map((x) => x.video_id)).toEqual(['a', 'c'])
  })
})

describe('D4: Home with projects.reuse', () => {
  const calls: string[] = []
  beforeEach(() => {
    resetFlags()
    calls.length = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.reuse'] })
      if (url.endsWith('/spend')) return ok({ month: { spent_usd: 0, ceiling_usd: 10, label: 'October' }, binding: null })
      if (url.endsWith('/pins') && method === 'GET') return ok({ pins: [] })
      if (url.includes('/pins/')) return url.includes('/video/') ? ok({ detail: 'Nope.' }, 500) : ok({ pinned: method === 'PUT' })
      if (url.endsWith('/projects?archived=true')) return ok({ projects: [{ ...FOLDERS[0], project_id: 'f9', name: 'Old', archived_at: '2026-10-10T00:00:00.000Z' }] })
      throw new Error(`unexpected ${method} ${url}`)
    }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('hides archived videos, pins a project, filters, and lists archived projects on ask', async () => {
    render(<ProjectsPage me={ME} projects={VIDEOS} folders={FOLDERS} onOpen={vi.fn()} onUpload={vi.fn()} onSample={vi.fn()} onDelete={vi.fn()} uploading={false} />)
    await screen.findByLabelText('Sort videos')
    expect(screen.getAllByTestId('video-card')).toHaveLength(3)
    expect(screen.queryByText('z.mp4')).toBeNull()
    expect(screen.getAllByTestId('video-card')[0]).toHaveTextContent('c.mp4')     // last edited first
    await userEvent.click(screen.getByRole('button', { name: 'Pin Diwali' }))
    const pinned = await screen.findByTestId('pinned')
    expect(within(pinned).getByRole('link', { name: 'Diwali' })).toHaveAttribute('href', '#p/f1')
    expect(calls).toContain('PUT /api/pins/project/f1')
    await userEvent.click(screen.getByRole('button', { name: /Needs attention · 2/ }))
    expect(screen.getAllByTestId('video-card').map((c) => c.textContent)).toEqual([expect.stringContaining('c.mp4'), expect.stringContaining('a.mp4')])
    await userEvent.selectOptions(screen.getByLabelText('Stage'), 'approved')
    expect(screen.getByText(/No video matches/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('archived-filter'))
    expect(screen.getByRole('link', { name: /Old/ })).toHaveAttribute('href', '#p/f9')
  })

  it('puts a failed pin back and says so', async () => {
    render(<ProjectsPage me={ME} projects={VIDEOS} folders={FOLDERS} onOpen={vi.fn()} onUpload={vi.fn()} onSample={vi.fn()} onDelete={vi.fn()} uploading={false} />)
    await userEvent.click(await screen.findByRole('button', { name: 'More for c.mp4' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Pin to Home' }))
    expect(await screen.findByText('Could not pin c.mp4.')).toBeInTheDocument()
    expect(screen.queryByTestId('pinned')).toBeNull()
  })
})

describe('D4: archiving a project', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('archives from the menu, shows the read-only banner, and unarchives', async () => {
    resetFlags()
    let archived: string | null = null
    const calls: string[] = []
    const project = () => ({ project_id: 'f1', name: 'Diwali', brief: '', settings: { autonomy: 'ask' }, ceiling_usd: null, spent_usd: 0, created_at: '2026-10-01T00:00:00.000Z', archived_at: archived })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.reuse'] })
      if (url.endsWith('/pins')) return ok({ pins: [] })
      if (url.endsWith('/projects/f1/archive')) { archived = method === 'POST' ? '2026-10-21T00:00:00.000Z' : null; return ok(project()) }
      if (url.endsWith('/projects/f1')) return ok({ project: project(), videos: [], voices: [], files: [], suggestions: [] })
      if (url.includes('/spend')) return ok({ project: null, month: null, binding: null })
      return ok({})
    }))
    const onDeleted = vi.fn()
    render(<ProjectPage me={ME} projectId="f1" onUpload={vi.fn()} uploading={false} error={null} onDeleted={onDeleted} />)
    await userEvent.click(await screen.findByRole('button', { name: 'More for this project' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Archive project' }))
    const banner = await screen.findByTestId('archived-banner')
    expect(banner).toHaveTextContent('This project is archived. Unarchive it to make changes.')
    expect(screen.getByRole('button', { name: '+ Upload to this project' })).toBeDisabled()
    expect(onDeleted).toHaveBeenCalled()
    await userEvent.click(within(banner).getByRole('button', { name: 'Unarchive' }))
    await waitFor(() => expect(screen.queryByTestId('archived-banner')).toBeNull())
    expect(calls).toEqual(expect.arrayContaining(['POST /api/projects/f1/archive', 'DELETE /api/projects/f1/archive']))
  })
})
