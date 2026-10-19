import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WhatISee } from './WhatISee'
import type { Understanding } from '../types'

const SEEN: Understanding = {
  version: 1,
  read: { format: 'sports clip', genre: 'Muay Thai bout', summary: 'Two fighters trade knees; blue goes down at 0:13.' },
  beats: [
    { at: 2.0, kind: 'cut', label: 'cut', confidence: 0.8, source: 'signal' },
    { at: 3.1, kind: 'visual', label: 'clinch broken', confidence: 0.8, source: 'vision' },
    { at: 11.8, kind: 'audio', label: 'crowd roar', confidence: 0.5, source: 'signal' },
    { at: 13.0, kind: 'visual', label: 'knockdown', confidence: 0.9, source: 'vision' },
  ],
  corrections: [],
  style: { line: 'Ringside commentary: present tense, short phrases, rising to the knockdown at 0:13.', accepted: false, by: 'voltage' },
}

describe('WhatISee (2026-10-20)', () => {
  it('shows the kind of piece, the summary and the beats; a beat seeks', async () => {
    const onSeek = vi.fn()
    render(<WhatISee seen={SEEN} onSeek={onSeek} onCorrect={vi.fn()} onStyle={vi.fn()} />)
    expect(screen.getByRole('button', { name: /What I see/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('sports clip · Muay Thai bout')).toBeInTheDocument()
    const beats = within(screen.getByRole('list', { name: 'Beats' })).getAllByRole('listitem')
    expect(beats).toHaveLength(3)                                   // cuts are counted, not listed
    expect(screen.getByText('1 cut')).toBeInTheDocument()
    expect(beats[1]).toHaveTextContent('crowd roar ?')              // an unsure beat says so
    await userEvent.click(screen.getByRole('button', { name: 'Go to 0:13.0: knockdown' }))
    expect(onSeek).toHaveBeenCalledWith(13.0)
  })

  it('takes a correction in words, or a beat marked not right', async () => {
    const onCorrect = vi.fn()
    render(<WhatISee seen={SEEN} onSeek={vi.fn()} onCorrect={onCorrect} onStyle={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Not right: knockdown at 0:13.0' }))
    expect(onCorrect).toHaveBeenLastCalledWith({ text: 'Not knockdown at 0:13.0', beat_at: 13.0, remove: true })
    await userEvent.click(screen.getByRole('button', { name: 'Correct it' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'What did Voltage get wrong?' }), 'This is Muay Thai{Enter}')
    expect(onCorrect).toHaveBeenLastCalledWith({ text: 'This is Muay Thai' })
  })

  it('offers the proposed style line to use as it is or change', async () => {
    const onStyle = vi.fn()
    render(<WhatISee seen={SEEN} onSeek={vi.fn()} onCorrect={vi.fn()} onStyle={onStyle} />)
    const style = screen.getByTestId('style')
    expect(style).toHaveTextContent('Style · proposed')
    await userEvent.click(within(style).getByRole('button', { name: 'Use it' }))
    expect(onStyle).toHaveBeenLastCalledWith(SEEN.style!.line)
    await userEvent.click(within(style).getByRole('button', { name: 'Change it' }))
    const box = within(style).getByRole('textbox', { name: 'How the new words should sound' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Calm, dry, no shouting.')
    await userEvent.click(within(style).getByRole('button', { name: 'Save style' }))
    expect(onStyle).toHaveBeenLastCalledWith('Calm, dry, no shouting.')
  })
})
