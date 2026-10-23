import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { FeedbackHost, openFeedback, context } from './FeedbackDialog'
import { noteJob, resetLastJob } from '../lib/lastJob'
import { KeyboardSheet } from './KeyboardSheet'
import { BetaFeedbackSection } from '../pages/admin/BetaFeedbackSection'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

describe('Item 11: Send feedback', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetLastJob(); window.location.hash = '' })

  it('attaches the route, the open video and the last job, and sends a message with a screenshot', async () => {
    window.location.hash = '#v/p12'
    noteJob('J3', '2026-10-23T10:00:00.000Z')
    noteJob('J7', '2026-10-23T10:05:00.000Z')
    noteJob('J5', '2026-10-23T10:01:00.000Z')
    expect(context()).toEqual({ route: '#v/p12', video_id: 'p12', job_id: 'J7' })
    let sent: FormData | null = null
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => { sent = init?.body as FormData; return ok({ id: 1, said: 'Thank you. We read every message.' }, 201) }))
    render(<FeedbackHost />)
    act(() => openFeedback())
    const dialog = await screen.findByTestId('feedback-dialog')
    expect(within(dialog).getByTestId('feedback-context')).toHaveTextContent('this page (#v/p12), video p12, job J7, the app version and your browser')
    const send = within(dialog).getByRole('button', { name: 'Send feedback' })
    expect(send).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Message'), 'The pane hid the Add button.')
    const shot = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'shot.png', { type: 'image/png' })
    await userEvent.upload(within(dialog).getByLabelText(/Screenshot/), shot)
    await userEvent.click(send)
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Thank you. We read every message.')
    const form = sent as unknown as FormData
    expect(form.get('message')).toBe('The pane hid the Add button.')
    expect(form.get('route')).toBe('#v/p12')
    expect(form.get('video_id')).toBe('p12')
    expect(form.get('job_id')).toBe('J7')
    expect(form.get('app_version')).toBe('dev')
    expect((form.get('screenshot') as File).name).toBe('shot.png')
  })

  it('refuses a screenshot that is not an image before sending', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({})))
    render(<FeedbackHost />)
    act(() => openFeedback())
    const dialog = await screen.findByTestId('feedback-dialog')
    await userEvent.upload(within(dialog).getByLabelText(/Screenshot/), new File(['x'], 'a.gif', { type: 'image/gif' }), { applyAccept: false })
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Attach a PNG, JPEG or WebP image.')
  })

  it('is in the help menu (the ? sheet)', async () => {
    render(<><KeyboardSheet open onClose={() => undefined} /><FeedbackHost /></>)
    await userEvent.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(await screen.findByTestId('feedback-dialog')).toBeInTheDocument()
  })

  it('lists feedback for admins with its status, a way to change it and the screenshot link', async () => {
    const calls: string[] = []
    let status = 'new'
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (init?.method === 'PUT') status = JSON.parse(String(init.body)).status
      const item = { id: 4, owner: 'google:sam', message: 'Broken', route: '#v/p1', video_id: 'p1', job_id: 'J2', app_version: 'dev', user_agent: 'UA', screenshot: true, screenshot_type: 'png', status, status_by: null, status_at: null, created_at: '2026-10-23T10:00:00.000Z' }
      const shown = url.includes('?status=') && !url.endsWith(`status=${status}`) ? [] : [item]
      return ok({ items: shown, counts: { new: status === 'new' ? 1 : 0, seen: status === 'seen' ? 1 : 0, done: 0 } })
    }))
    render(<BetaFeedbackSection card="" />)
    await userEvent.click(screen.getByRole('button', { name: 'All' }))
    const row = await screen.findByTestId('beta-row')
    expect(row).toHaveTextContent('Broken')
    expect(within(row).getByRole('link', { name: 'Open the screenshot' })).toHaveAttribute('href', '/api/admin/beta-feedback/4/screenshot')
    await userEvent.click(within(row).getByRole('button', { name: 'Mark seen' }))
    expect(calls).toContain('PUT /api/admin/beta-feedback/4 {"status":"seen"}')
    expect(await screen.findByRole('button', { name: 'Mark done' })).toBeInTheDocument()
  })
})
