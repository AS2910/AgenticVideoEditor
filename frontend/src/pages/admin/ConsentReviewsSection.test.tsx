import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentReviewsSection } from './ConsentReviewsSection'
import { ADMIN_SECTIONS } from './sections'
import type { ConsentReview } from '../../api'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ITEM: ConsentReview = {
  id: 'cv_1', owner: 'google:sam', video_id: 'p1', speaker: 'A', sentence: 'Purple kettle river tiger window salad pencil morning.',
  status: 'review', reason: 'The voice is close but not a clear match, so a person will listen to the recording.',
  heard: 'purple kettle river tiger window salad pencil morning', wer: 0, similarity: 0.88, seconds: 5.2, rule: 'voice',
  asr_model: 'openai:whisper-1', speaker_model: 'microsoft/wavlm-base-plus-sv', pass_at: 0.92, review_from: 0.84,
  created_at: '2026-10-24T10:00:00.000Z', checked_at: '2026-10-24T10:00:05.000Z', reviewed_by: null, review_reason: '', reviewed_at: null, has_recording: true,
}

describe('Run 4 item 2: consent reviews on the admin page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists a close check with what was heard, the scores and both recordings, then approves it with a reason', async () => {
    const calls: string[] = []
    let items = [ITEM]
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (init?.method === 'POST') { items = []; return ok({ ...ITEM, status: 'passed', reviewed_by: 'google:ada', review_reason: 'Same voice' }) }
      return ok({ items, waiting: items.length })
    }))
    render(<ConsentReviewsSection card="" />)
    const row = await screen.findByTestId('consent-review')
    expect(row).toHaveTextContent('Purple kettle river tiger')
    expect(row).toHaveTextContent('Voice match 0.88 (passes at 0.92, review from 0.84)')
    expect(row).toHaveTextContent('word errors 0%')
    expect(row.querySelectorAll('audio')[0]).toHaveAttribute('src', '/api/admin/consent-reviews/cv_1/recording')
    expect(row.querySelectorAll('audio')[1]).toHaveAttribute('src', '/api/admin/consent-reviews/cv_1/source')
    expect(screen.getByRole('button', { name: 'Waiting · 1' })).toHaveAttribute('aria-pressed', 'true')
    const approve = within(row).getByRole('button', { name: 'Approve' })
    expect(approve).toBeDisabled()                                  // a reason first
    await userEvent.type(within(row).getByLabelText('Why'), 'Same voice')
    await userEvent.click(approve)
    expect(calls).toContain('POST /api/admin/consent-reviews/cv_1 {"decision":"approve","reason":"Same voice"}')
    expect(await screen.findByText('Nothing waiting.')).toBeInTheDocument()
  })

  it('shows the decided ones with who decided and why', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ok(url.includes('status=decided')
      ? { items: [{ ...ITEM, status: 'failed', reviewed_by: 'google:ada', review_reason: 'Two voices in it', reviewed_at: '2026-10-24T11:00:00.000Z' }], waiting: 0 }
      : { items: [], waiting: 0 })))
    render(<ConsentReviewsSection card="" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Decided' }))
    const row = await screen.findByTestId('consent-review')
    expect(row).toHaveTextContent('Rejected')
    expect(row).toHaveTextContent('google:ada')
    expect(row).toHaveTextContent('Two voices in it')
    expect(within(row).queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('is one of the admin sections', () => {
    expect(ADMIN_SECTIONS.map((s) => s.id)).toContain('consent')
  })
})
