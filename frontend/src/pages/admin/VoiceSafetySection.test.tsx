import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NoGoHoldsQueue } from './NoGoHoldsQueue'
import { NoGoVoicesList } from './NoGoVoicesList'
import { ADMIN_SECTIONS } from './sections'
import type { NoGoHold, NoGoVoice } from './noGoApi'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const HOLD: NoGoHold = {
  id: 'ngh_1', owner: 'google:sam', video_id: 'p1', speaker_label: 'A', speaker_name: 'Asha', subject: 'video:p1:A',
  no_go_id: 'ngv_1', no_go_name: 'A. Famous Person', score: 0.88, model: 'microsoft/wavlm-base-plus-sv', status: 'waiting',
  reason: '', decided_by: null, decided_at: null, created_at: '2026-10-31T10:00:00.000Z', has_audio: true, block_at: 0.92, review_from: 0.84,
}
const VOICE: NoGoVoice = {
  id: 'ngv_1', name: 'A. Famous Person', reason: 'Public figure', added_by: 'google:ada', created_at: '2026-10-31T09:00:00.000Z',
  model: 'microsoft/wavlm-base-plus-sv', source: 'upload', source_ref: 'famous.wav', seconds: 6.2, dims: 512,
}
const LIST = (voices: NoGoVoice[], model_available = true) => ({ voices, block_at: 0.92, review_from: 0.84, model: 'wavlm', model_available })

describe('Voice consent V1 step 5: the borderline no-go queue', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows a close clone with its score, the bands and the clip, and approves it with a reason', async () => {
    const calls: string[] = []
    let items = [HOLD]
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (init?.method === 'POST') { items = []; return ok({ ...HOLD, status: 'approved' }) }
      return ok({ items, waiting: items.length })
    }))
    render(<NoGoHoldsQueue />)
    const row = await screen.findByTestId('no-go-hold')
    expect(row).toHaveTextContent('Close to A. Famous Person')
    expect(row).toHaveTextContent('Voice match 0.88 (blocked at 0.92, review from 0.84)')
    expect(row).toHaveTextContent('Asha')
    expect(row.querySelector('audio')).toHaveAttribute('src', '/api/admin/no-go-holds/ngh_1/audio')
    const approve = within(row).getByRole('button', { name: 'Approve' })
    expect(approve).toBeDisabled()                                   // a reason first
    await userEvent.type(within(row).getByLabelText('Why'), 'Different person')
    await userEvent.click(approve)
    expect(calls).toContain('POST /api/admin/no-go-holds/ngh_1 {"decision":"approve","reason":"Different person"}')
    expect(await screen.findByText('Nothing waiting.')).toBeInTheDocument()
  })

  it('shows the decided ones with who decided and why, and no buttons', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ok(url.includes('status=decided')
      ? { items: [{ ...HOLD, status: 'rejected', decided_by: 'google:ada', reason: 'It is them', decided_at: '2026-10-31T11:00:00.000Z', has_audio: false }], waiting: 0 }
      : { items: [], waiting: 0 })))
    render(<NoGoHoldsQueue />)
    await userEvent.click(await screen.findByRole('button', { name: 'Decided' }))
    const row = await screen.findByTestId('no-go-hold')
    expect(row).toHaveTextContent('Rejected')
    expect(row).toHaveTextContent('It is them')
    expect(within(row).queryByRole('button', { name: 'Approve' })).toBeNull()
  })
})

describe('Voice consent V1 step 5: the no-go list', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('starts empty and adds a voice from a clip with a reason', async () => {
    const calls: { method: string; url: string; body: unknown }[] = []
    let voices: NoGoVoice[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body })
      if (init?.method === 'POST') { voices = [VOICE]; return ok(VOICE, 201) }
      return ok(LIST(voices))
    }))
    render(<NoGoVoicesList />)
    expect(await screen.findByText('The list is empty. Add a voice when an abuse report names a public figure.')).toBeInTheDocument()
    const add = screen.getByRole('button', { name: 'Add to the list' })
    expect(add).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Whose voice'), 'A. Famous Person')
    await userEvent.type(screen.getByLabelText('Why'), 'Public figure')
    await userEvent.upload(screen.getByLabelText('The clip'), new File(['x'], 'famous.wav', { type: 'audio/wav' }))
    await userEvent.click(add)
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toBe('/api/admin/no-go-voices')
    const form = post.body as FormData
    expect([form.get('name'), form.get('reason'), (form.get('file') as File).name]).toEqual(['A. Famous Person', 'Public figure', 'famous.wav'])
    expect(await screen.findByTestId('no-go-voice')).toHaveTextContent('From the clip famous.wav, 6.2 s')
  })

  it('adds from a reported export by its abuse report number', async () => {
    const posted: FormData[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { posted.push(init.body as FormData); return ok({ ...VOICE, source: 'export' }, 201) }
      return ok(LIST([]))
    }))
    render(<NoGoVoicesList />)
    await userEvent.click(await screen.findByRole('button', { name: 'A reported export' }))
    await userEvent.type(screen.getByLabelText('Whose voice'), 'Reported')
    await userEvent.type(screen.getByLabelText('Why'), 'Abuse report')
    await userEvent.type(screen.getByLabelText('Export mark or abuse report number'), '42')
    await userEvent.click(screen.getByRole('button', { name: 'Add to the list' }))
    expect(posted[0].get('abuse_report_id')).toBe('42')
    expect(posted[0].get('mark')).toBeNull()
  })

  it('removes a voice only with a reason', async () => {
    const calls: string[] = []
    let voices = [VOICE]
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${typeof init?.body === 'string' ? init.body : ''}`.trim())
      if (init?.method === 'DELETE') { voices = []; return ok({ removed: 'ngv_1', name: VOICE.name, holds_closed: 0 }) }
      return ok(LIST(voices))
    }))
    const changed = vi.fn()
    render(<NoGoVoicesList onChange={changed} />)
    const row = await screen.findByTestId('no-go-voice')
    await userEvent.click(within(row).getByRole('button', { name: 'Remove' }))
    const confirm = within(row).getByRole('button', { name: 'Remove' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(row).getByLabelText('Why remove it'), 'Added by mistake')
    await userEvent.click(confirm)
    expect(calls).toContain('DELETE /api/admin/no-go-voices/ngv_1 {"reason":"Added by mistake"}')
    expect(changed).toHaveBeenCalled()
    expect(await screen.findByText(/The list is empty/)).toBeInTheDocument()
  })

  it('says when the speaker model is missing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(LIST([VOICE], false))))
    render(<NoGoVoicesList />)
    expect(await screen.findByRole('note')).toHaveTextContent('The speaker model is not available here')
  })

  it('is part of the Voice safety section on the admin page', () => {
    expect(ADMIN_SECTIONS.map((s) => s.id)).toContain('voice-safety')
  })
})
