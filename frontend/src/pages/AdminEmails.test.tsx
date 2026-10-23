import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminEmails } from './AdminEmails'
import { parseRoute, hrefFor } from '../lib/route'
import { resetFlags } from '../flags/useFlags'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const KINDS = [{ kind: 'verify_email', label: 'Verify address' }, { kind: 'job_failed', label: 'Job failed' }]
const MAIL: Record<string, { subject: string; html: string; text: string }> = {
  verify_email: { subject: 'Confirm your email for Voltage', html: '<!doctype html><p>Confirm <script>x()</script></p>', text: 'Hi,\n\nOpen this link to confirm.' },
  job_failed: { subject: 'The export of ad.mp4 failed', html: '<!doctype html><p>Failed</p>', text: 'What happened: ffmpeg stopped.' },
}

describe('Item 9: the email preview', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags() })

  it('routes #admin/emails', () => {
    expect(parseRoute('#admin/emails')).toEqual({ page: 'adminEmails' })
    expect(hrefFor({ page: 'adminEmails' })).toBe('#admin/emails')
  })

  it('lists the kinds, shows the HTML in a sandboxed frame and the text beside it, and switches', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/admin/emails/preview')) return ok({ kinds: KINDS })
      const kind = url.split('/').pop() as string
      if (MAIL[kind]) return ok({ kind, label: KINDS.find((k) => k.kind === kind)?.label, ...MAIL[kind] })
      return ok({ flags: [] })
    }))
    render(<AdminEmails me={null} />)
    const preview = await screen.findByTestId('email-preview')
    expect(within(preview).getByRole('heading', { name: 'Confirm your email for Voltage' })).toBeInTheDocument()
    const frame = within(preview).getByTestId('email-html')
    expect(frame.getAttribute('sandbox')).toBe('')
    expect(frame.getAttribute('srcdoc')).toContain('Confirm')
    expect(frame).toHaveAccessibleName('Verify address: the HTML email')
    expect(within(preview).getByTestId('email-text')).toHaveTextContent('Open this link to confirm.')
    expect(screen.getByRole('button', { name: 'Verify address' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Job failed' }))
    expect(await screen.findByRole('heading', { name: 'The export of ad.mp4 failed' })).toBeInTheDocument()
    expect(screen.getByTestId('email-text')).toHaveTextContent('What happened: ffmpeg stopped.')
    expect(calls.every((c) => c.startsWith('GET '))).toBe(true)             // it never sends
  })

  it('says so when the emails cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.includes('/admin/emails') ? ok({ detail: 'Not found' }, 404) : ok({ flags: [] }))))
    render(<AdminEmails me={null} />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
