import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentSheet } from './ConsentSheet'
import { AbuseReport } from './AbuseReport'
import { WithdrawConsent } from './WithdrawConsent'
import { LegalPage } from '../pages/LegalPage'
import { YourData } from '../pages/YourData'
import { parseRoute, hrefFor } from '../lib/route'
import { Tip } from '../guides/Tip'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

function serve(handle: (url: string, init?: RequestInit) => unknown) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    const out = handle(url, init)
    return out && typeof out === 'object' && 'ok' in (out as object) && 'status' in (out as object) ? out as Response : ok(out)
  }))
  return calls
}

describe('G6: consent with liveness', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks for the sentence read aloud before Yes works, and passes the attempt to consent', async () => {
    let status = 'failed'
    serve((url) => {
      if (url.endsWith('/videos/p1/liveness')) return { attempt_id: 'lv_1', sentence: 'I agree to let Voltage use my voice. My code is 4 7 1 9.', test_mode: true }
      if (url.includes('/liveness/lv_1')) return { attempt_id: 'lv_1', status, reason: status === 'passed' ? 'Passed in test mode: the recording was kept, the words were not checked.' : 'That recording is too short. Read the whole sentence aloud.', test_mode: true }
      return {}
    })
    const onConfirm = vi.fn()
    render(<ConsentSheet who="Jeevan" livenessVideoId="p1" onConfirm={onConfirm} onCancel={() => {}} />)
    expect(await screen.findByTestId('liveness-sentence')).toHaveTextContent('My code is 4 7 1 9.')
    expect(screen.getByText('Test mode')).toBeInTheDocument()
    const yes = screen.getByRole('button', { name: 'Yes, I have it' })
    expect(yes).toBeDisabled()
    const file = new File(['RIFF'], 'me.wav', { type: 'audio/wav' })
    await userEvent.upload(screen.getByLabelText('Upload a recording'), file)
    expect(await screen.findByTestId('liveness-note')).toHaveTextContent('too short')
    expect(yes).toBeDisabled()
    status = 'passed'
    await userEvent.upload(screen.getByLabelText('Upload a recording'), file)
    expect(await screen.findByText(/^Recorded\. Passed in test mode/)).toBeInTheDocument()
    await waitFor(() => expect(yes).toBeEnabled())
    await userEvent.click(yes)
    expect(onConfirm).toHaveBeenCalledWith('lv_1')
  })

  it('without liveness (flag off) the sheet is as before', () => {
    const onConfirm = vi.fn()
    render(<ConsentSheet who="Jeevan" onConfirm={onConfirm} onCancel={() => {}} />)
    expect(screen.queryByTestId('liveness')).toBeNull()
    expect(screen.getByRole('button', { name: 'Yes, I have it' })).toBeEnabled()
  })
})

describe('G6: withdraw consent, abuse reports, legal pages, your data', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('withdraws after one inline question and says what happened', async () => {
    const calls = serve(() => ({ withdrawn: true, deleted: 1, failed: [], said: "Consent withdrawn. The speaker's voice clone was deleted at the voice service." }))
    const onWithdrawn = vi.fn()
    render(<WithdrawConsent videoId="p1" onWithdrawn={onWithdrawn} />)
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw consent now' }))
    const group = screen.getByRole('group', { name: 'Withdraw consent?' })
    expect(group.querySelectorAll('button')[1]).toHaveTextContent('Withdraw and delete the clone')
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw and delete the clone' }))
    expect(await screen.findByText("Consent withdrawn. The speaker's voice clone was deleted at the voice service.")).toBeInTheDocument()
    expect(onWithdrawn).toHaveBeenCalled()
    expect(calls).toContain('POST /api/videos/p1/consent/withdraw')
  })

  it('the abuse form shows only where reports are taken, and sends', async () => {
    let open = false
    const calls = serve((url) => (url.endsWith('/abuse-reports/open') ? { open } : { report_id: 1, said: 'Thank you. We read every report and act on it.' }))
    const { unmount } = render(<AbuseReport compact location="http://x/#s/t" />)
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByRole('button', { name: 'Report misuse' })).toBeNull()
    unmount()
    open = true
    render(<AbuseReport compact location="http://x/#s/t" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Report misuse' }))
    const send = screen.getByRole('button', { name: 'Send report' })
    expect(send).toBeDisabled()
    await userEvent.click(screen.getByLabelText("A public figure's voice"))
    await userEvent.type(screen.getByLabelText('What happened (optional)'), 'It is a famous actor')
    await userEvent.click(send)
    expect(await screen.findByTestId('abuse-done')).toHaveTextContent('Thank you. We read every report and act on it.')
    expect(calls).toContain('POST /api/abuse-reports')
  })

  it('routes the policies and marks each as a draft for legal review', () => {
    serve(() => ({ open: false }))
    expect(parseRoute('#terms')).toEqual({ page: 'legal', doc: 'terms' })
    expect(parseRoute('#acceptable-use')).toEqual({ page: 'legal', doc: 'acceptable-use' })
    expect(hrefFor({ page: 'legal', doc: 'privacy' })).toBe('#privacy')
    render(<LegalPage doc="privacy" />)
    expect(screen.getByTestId('legal-draft')).toHaveTextContent('Draft, needs legal review')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Privacy policy')
    expect(document.body.textContent).not.toContain('—')
  })

  it('downloads your data as a job and links the zip when ready; delete goes to the account delete', async () => {
    let requests: unknown[] = []
    serve((_url, init) => {
      if (init?.method === 'POST') { requests = [{ id: 1, kind: 'export', status: 'done', job_id: 'j9', created_at: '', done_at: '', job: { job_id: 'j9', status: 'done', step_label: 'Ready', error_text: null } }]; return { request: requests[0] } }
      return { requests }
    })
    const onDelete = vi.fn()
    render(<YourData onDelete={onDelete} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Download my data' }))
    expect(await screen.findByRole('link', { name: 'Download zip' })).toHaveAttribute('href', '/api/me/data-export/j9/download')
    await userEvent.click(screen.getByRole('button', { name: 'Delete my data' }))
    expect(onDelete).toHaveBeenCalled()
  })
})

describe('9e: tips for the G6 consent and withdraw flows', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the read-aloud tip inside the consent dialog, where its Got it can be reached', async () => {
    serve((url) => (url.endsWith('/videos/p1/liveness') ? { attempt_id: 'lv_1', sentence: 'My code is 4 7 1 9.', test_mode: true } : {}))
    render(<ConsentSheet who="Jeevan" livenessVideoId="p1" onConfirm={() => {}} onCancel={() => {}} />)
    const dialog = await screen.findByRole('dialog')
    const tip = within(dialog).getByRole('status', { name: 'Tip: Read aloud' })
    expect(tip).toHaveTextContent('reads this sentence once, live')
    expect(tip.className).not.toMatch(/\bfixed\b/)
    expect(within(tip).getByRole('link', { name: /The speaker's own voice and consent/ })).toHaveAttribute('href', '#help/the-speakers-own-voice-and-consent')
    expect(within(dialog).getByRole('button', { name: 'Got it' })).toBeEnabled()     // inside the focus trap
  })

  it('points the withdraw tip at the Withdraw consent now row', async () => {
    serve(() => ({}))
    render(<><WithdrawConsent videoId="p1" onWithdrawn={() => {}} /><Tip id="first-withdraw-consent" target="withdraw-consent" /></>)
    expect(screen.getByTestId('withdraw-consent')).toHaveAttribute('data-tour', 'withdraw-consent')
    const tip = screen.getByRole('status', { name: 'Tip: Withdraw consent' })
    expect(tip).toHaveTextContent('the voice clone is deleted at once')
    expect(within(tip).getByRole('link', { name: /Withdrawing consent/ })).toHaveAttribute('href', '#help/withdrawing-consent')
  })
})
