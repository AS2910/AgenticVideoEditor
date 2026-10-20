import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LineDoc } from './LineDoc'
import { shortenSentence, shortenUsd } from '../transcript/fit'
import { splitTags } from '../transcript/tags'
import type { FitFailure, PlanItem } from '../types'

const failure = (over: Partial<FitFailure> = {}): FitFailure => ({
  reason: 'too_long', needs: 3.0, has: 2.3, tried: ["trimmed the take's pauses", 'started 150 ms early'], syllables: 11, budget: 8,
  cost_usd: 0.03, text: '', eased_candidate_id: 'c9', ease_s: 0.74, ...over,
})
/** An added line on the silent boxing clip that ran long for its gap. */
const long = (id: string, start: number, words: string, over: Partial<FitFailure> = {}): PlanItem => ({
  item_id: id, selection: { start, end: start + 2.3 }, old_text: '', new_text: words, speaker: null, mix: 'layer', reason: '',
  kind: 'planned', enabled: true, status: 'failed', fit: null, candidate: null, edit_id: null, question: null,
  error: 'Too long for its gap: needs 3.0 s, has 2.3 s.', note: null, progress: null, fit_failure: failure({ text: words, ...over }),
})
const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onAdd: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onRemove: vi.fn(), onHearTake: vi.fn(),
  onShorten: vi.fn(), onShortenAll: vi.fn(), onEase: vi.fn(),
})
const doc = (items: PlanItem[]) => {
  const h = handlers()
  render(<LineDoc statements={[]} duration={16.8} currentTime={0} items={items} {...h} />)
  return h
}

describe('A line too long for its gap (p61)', () => {
  it('is one compact row: its words, a delivery chip for its tag, one quiet reason and three actions', async () => {
    const h = doc([long('i3', 7.1, '[curious] Back to the centre now. Red shorts stalking.')])
    const row = screen.getByRole('listitem', { name: 'Proposed line at 0:07' })
    // The tag is never a word; it is a chip beside the line.
    expect(within(row).queryByText(/\[curious\]/)).toBeNull()
    expect(within(row).getByText('Back to the centre now. Red shorts stalking.')).toBeInTheDocument()
    expect(within(row).getByTestId('delivery-chip')).toHaveTextContent('curious')
    expect(within(row).getByTestId('fit-reason')).toHaveTextContent('3.0 s for a 2.3 s gap')
    expect(within(row).queryByText(/needs 3.0 s, has 2.3 s/)).toBeNull()          // said once, quietly
    const acts = within(row).getByRole('group', { name: 'What to do with the line at 0:07' })
    expect(within(acts).getAllByRole('button').map((b) => b.textContent)).toEqual(['Shorten', 'Let the picture ease (+0.7 s)', 'Discard'])
    expect(within(row).queryByRole('button', { name: 'Ask Voltage to try again' })).toBeNull()
    await userEvent.click(within(acts).getByRole('button', { name: 'Let the picture ease (+0.7 s)' }))
    expect(h.onEase).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i3' }))
    await userEvent.click(within(acts).getByRole('button', { name: 'Shorten' }))
    expect(h.onShorten).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i3' }))
    expect(screen.queryByTestId('fit-banner')).toBeNull()                         // one line: no banner
  })

  it('offers the picture ease only when a voiced take was kept for it', () => {
    doc([long('i3', 7.1, 'Back to the centre now.', { eased_candidate_id: null, ease_s: null })])
    const acts = screen.getByRole('group', { name: 'What to do with the line at 0:07' })
    expect(within(acts).getAllByRole('button').map((b) => b.textContent)).toEqual(['Shorten', 'Discard'])
  })

  it('several lines failing for the same reason collapse into one banner above them', async () => {
    const items = [long('i1', 0.2, 'Referee breaks the clinch, he wants them apart.'), long('i2', 3.2, '[excited] Blue ties him up all round!'),
      long('i3', 7.1, 'Back to the centre now.'), long('i4', 10.5, '[shouting] Blue goes DOWN!')]
    const h = doc(items)
    const banners = screen.getAllByTestId('fit-banner')
    expect(banners).toHaveLength(1)
    const banner = banners[0]
    expect(banner).toHaveTextContent('4 lines are too long for their gaps.')
    // Above the first of them.
    const list = screen.getAllByRole('listitem')
    expect(list.findIndex((el) => el.contains(banner))).toBeLessThan(list.findIndex((el) => el.getAttribute('aria-label') === 'Proposed line at 0:00'))
    expect(within(banner).getAllByRole('button').map((b) => b.textContent)).toEqual(['Shorten all and voice (~$0.12)', 'Let the picture ease', 'Discard all'])
    await userEvent.click(within(banner).getByRole('button', { name: 'Shorten all and voice (~$0.12)' }))
    expect(h.onShortenAll).toHaveBeenCalledTimes(1)
    expect(h.onShortenAll.mock.calls[0][0].map((i: PlanItem) => i.item_id)).toEqual(['i1', 'i2', 'i3', 'i4'])
    await userEvent.click(within(banner).getByRole('button', { name: 'Discard all' }))
    expect(h.onDiscard).toHaveBeenCalledTimes(4)
  })

  it('says to Voltage, in one sentence, every line to shorten and its syllables, tags left out', () => {
    const items = [long('i1', 0.2, '[excited] Red catches him!'), long('i2', 3.2, 'Blue is down.', { budget: 4, has: 1.8 })]
    expect(shortenUsd(items)).toBeCloseTo(0.06)
    expect(shortenSentence(items)).toBe('Shorten these 2 lines so each fits its gap, and voice each again once: '
      + 'i1 (“Red catches him!”, about 8 syllables for 2.3 s); i2 (“Blue is down.”, about 4 syllables for 1.8 s).')
    expect(shortenSentence([items[1]])).toBe('Shorten i2 (“Blue is down.”, about 4 syllables for 1.8 s) so it fits its gap, and voice it again.')
  })

  it('shows audio tags as delivery chips, never as words', () => {
    expect(splitTags('[curious] So... [whispers] here? [curious]')).toEqual({ words: 'So... here?', tags: ['curious', 'whispers'] })
    expect(splitTags('No tags at all.')).toEqual({ words: 'No tags at all.', tags: [] })
  })
})
