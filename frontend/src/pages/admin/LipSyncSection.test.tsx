import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LipSyncSection } from './LipSyncSection'
import { ADMIN_SECTIONS } from './sections'
import type { LipSyncTrial, LipSyncVideo } from './lipsyncApi'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const conf = (score: number | null) => ({ score, method: 'motion' as const, detail: {} })
const TRIAL: LipSyncTrial = {
  id: 't1', at: '2026-10-27T10:00:00Z', by: 'local', line: 1, provider: 'fake', heard: "the line's own sound (no take yet)",
  window: { start: 0.5, end: 2.0, send_start: 0, send_end: 2.5 },
  original: { sha256: 'a'.repeat(64), confidence: conf(0.83) }, result: { sha256: 'b'.repeat(64), confidence: conf(0.14) },
  compare: { verdict: 'below', say: 'Less well synced than the original.' }, usd: 0, notes: ['The fake provider marks the span; it does not move the mouth.'], seconds: 4.1,
}
const VIDEO: LipSyncVideo = {
  video_id: 'p3', filename: 'shop.mp4', duration: 9, status: 'done', seconds: 1.4, trials: [],
  lines: [
    { index: 1, start: 0.5, end: 2.0, text: 'Hi, I want to buy groceries.', on_camera: 'on_camera', detail: { why: 'A face is on screen and its mouth moves with this line.' } },
    { index: 2, start: 2.4, end: 4.0, text: 'Sure, sir.', on_camera: 'off_camera', detail: { why: 'No face on screen for this line.' } },
  ],
}

describe('Run 5 item 10: the lip-sync review on the admin page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is one entry in the admin sections', () => {
    expect(ADMIN_SECTIONS.map((s) => s.id)).toContain('lipsync')
  })

  it('loads a video, shows who is on camera per line, runs a line and shows both sides scored', async () => {
    const calls: string[] = []
    let trials: LipSyncTrial[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url === '/api/admin/lipsync') return ok({ selected: 'off', providers: [{ name: 'fake', available: true }, { name: 'sync_so', available: false }], handle_seconds: 0.5, measure: 'motion' })
      if (init?.method === 'POST') { trials = [TRIAL]; return ok(TRIAL) }
      return ok({ ...VIDEO, trials })
    }))
    render(<LipSyncSection card="" />)
    expect(await screen.findByTestId('lipsync-status')).toHaveTextContent('Provider in the product: none yet. Each span is sent with 0.5 s either side.')
    await userEvent.type(screen.getByLabelText('Video id'), 'p3')
    await userEvent.click(screen.getByRole('button', { name: 'Load' }))
    const lines = await screen.findAllByTestId('lipsync-line')
    expect(lines[0]).toHaveTextContent('On camera')
    expect(lines[1]).toHaveTextContent('Off camera')
    await userEvent.click(within(lines[0]).getByRole('button', { name: 'Try line 1' }))
    expect(calls).toContain('POST /api/admin/lipsync/videos/p3/trials {"line":1,"provider":"fake"}')
    const trial = await screen.findByTestId('lipsync-trial')
    expect(trial).toHaveTextContent('Less well synced than the original.')
    expect(trial).toHaveTextContent('Confidence 0.83 (mouth motion)')
    expect(trial).toHaveTextContent('Confidence 0.14 (mouth motion)')
    const videos = trial.querySelectorAll('video')
    expect(videos[0]).toHaveAttribute('src', `/api/admin/lipsync/videos/p3/files/${'a'.repeat(64)}`)
    expect(videos[1]).toHaveAttribute('src', `/api/admin/lipsync/videos/p3/files/${'b'.repeat(64)}`)
  })

  it('says why in words when a provider is off', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/admin/lipsync') return ok({ selected: 'off', providers: [{ name: 'fake', available: true }], handle_seconds: 0.5, measure: 'motion' })
      if (init?.method === 'POST') return ok({ detail: 'Lip-sync by sync_so is off. Only the fake runs without a key.' }, 422)
      return ok(VIDEO)
    }))
    render(<LipSyncSection card="" />)
    await userEvent.type(screen.getByLabelText('Video id'), 'p3')
    await userEvent.click(screen.getByRole('button', { name: 'Load' }))
    await userEvent.click((await screen.findAllByRole('button', { name: /Try line/ }))[0])
    expect(await screen.findByRole('alert')).toHaveTextContent('Only the fake runs without a key.')
  })
})
