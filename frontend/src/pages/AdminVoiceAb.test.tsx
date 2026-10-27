import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminVoiceAb } from './AdminVoiceAb'
import { hrefFor, parseRoute } from '../lib/route'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const SCORES = {
  old: { sim_o: 0.71, utmos: 3.9, prosody_distance: 1.4, loudness_delta_db: -2.5, duration_error_s: 0.2 },
  new: { sim_o: 0.78, utmos: 4.1, prosody_distance: 0.6, loudness_delta_db: 0.3, duration_error_s: 0.1 },
}
const TRIAL = { id: 't1', speaker: 'A', before: 'That summer day was very hot', after: 'That spring day was very hot', start: 10.96, end: 14.9, voted: false }
const PAGE = { run: 'r1', runs: ['r1'], trials: [TRIAL], tally: { old: 0, new: 0, same: 0 }, voters: 0 }

describe('run 5 item 7: the voice A/B page', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('routes #admin/voice-ab', () => {
    expect(parseRoute('#admin/voice-ab')).toEqual({ page: 'adminVoiceAb' })
    expect(hrefFor({ page: 'adminVoiceAb' })).toBe('#admin/voice-ab')
  })

  it('is blind until a vote, then says which was which with the scores', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (init?.method === 'POST') {
        return ok({ ...PAGE, trials: [{ ...TRIAL, voted: true, choice: 'b', a_is: 'old', scores: SCORES }], tally: { old: 0, new: 1, same: 0 }, voters: 1 })
      }
      return ok(PAGE)
    }))
    render(<AdminVoiceAb me={null} />)
    const trial = await screen.findByTestId('voice-ab-trial')
    expect(trial).toHaveTextContent('Was: That summer day was very hot')
    expect(within(trial).getByLabelText('Line 1: A')).toHaveAttribute('src', '/api/admin/voice-ab/r1/t1/a')
    expect(within(trial).getByLabelText('Line 1: the original')).toHaveAttribute('src', '/api/admin/voice-ab/r1/t1/original')
    expect(screen.queryByTestId('voice-ab-reveal')).toBeNull()
    expect(trial).not.toHaveTextContent('old way')
    await userEvent.click(within(trial).getByRole('button', { name: 'B' }))
    const reveal = await screen.findByTestId('voice-ab-reveal')
    expect(reveal).toHaveTextContent('A was the old way, B was the new way. You picked B (the new way).')
    expect(reveal).toHaveTextContent('0.60')
    expect(screen.getByTestId('voice-ab-tally')).toHaveTextContent('New way 1 · Old way 0 · Same 0 · from 1 person')
    expect(calls).toContain('POST /api/admin/voice-ab/r1/t1/vote {"choice":"b"}')
    // The vote is the last thing on the card.
    const buttons = within(screen.getByTestId('voice-ab-trial')).getAllByRole('button')
    expect(buttons[buttons.length - 1]).toHaveTextContent('Can’t tell')
  })

  it('says so when there are no trials yet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ run: null, runs: [], trials: [], tally: { old: 0, new: 0, same: 0 }, voters: 0 })))
    render(<AdminVoiceAb me={null} />)
    expect(await screen.findByText('No trials yet. Run the voice tone eval to make some.')).toBeInTheDocument()
  })
})
