import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NotificationBell } from './NotificationBell'
import { NotificationsPage } from '../pages/NotificationsPage'
import { resetFlags } from '../flags/useFlags'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const AT = new Date().toISOString()
const ITEMS = [
  { id: 2, kind: 'job_failed', title: 'The export of ad.mp4 failed.', body: 'ffmpeg stopped.', link: '#v/p1', video_id: 'p1', project_id: null, created_at: AT, read: false },
  { id: 1, kind: 'approval', title: 'Priya approved ad.mp4 v5.', body: '', link: '#v/p1', video_id: 'p1', project_id: null, created_at: AT, read: true },
]
const KINDS = [
  { kind: 'job_done', label: 'Long work finished', help: 'x', in_app: true, email: false },
  { kind: 'spend_alert', label: 'Spend alerts', help: 'y', in_app: true, email: true },
]

describe('G4: the bell', () => {
  beforeEach(() => resetFlags())
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('stays hidden with the flag off', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ flags: [] })))
    const { container } = render(<NotificationBell />)
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the unread count, lists items, marks all read and opens one', async () => {
    const calls: string[] = []
    let unread = 1
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.includes('/me/flags')) return ok({ flags: ['golive.g4'] })
      if (url.endsWith('/count')) return ok({ unread })
      if (url.endsWith('/read')) { unread = 0; return ok({ unread: 0 }) }
      return ok({ items: ITEMS, unread })
    }))
    render(<NotificationBell />)
    const bell = await screen.findByRole('button', { name: 'Notifications, 1 unread' })
    await userEvent.click(bell)
    const panel = await screen.findByTestId('bell-panel')
    const items = await within(panel).findAllByTestId('bell-item')
    expect(items[0]).toHaveTextContent('The export of ad.mp4 failed.ffmpeg stopped.')
    await userEvent.click(within(panel).getByRole('button', { name: 'Mark all read' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument())
    expect(calls).toContain('POST /api/me/notifications/read {"all":true}')
    await userEvent.click(within(panel).getAllByTestId('bell-item')[1])
    expect(window.location.hash).toBe('#v/p1')
    expect(screen.queryByTestId('bell-panel')).toBeNull()
  })

  it('settings save per kind and channel', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.includes('/me/flags')) return ok({ flags: ['golive.g4'] })
      if (init?.method === 'PUT') return ok({ kinds: KINDS.map((k) => (k.kind === 'job_done' ? { ...k, email: true } : k)) })
      return ok({ kinds: KINDS })
    }))
    render(<NotificationsPage me={null} />)
    const toggle = await screen.findByRole('switch', { name: 'Long work finished by email' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(toggle)
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'))
    expect(calls).toContain('PUT /api/me/notifications/settings {"job_done":{"email":true}}')
  })
})
