import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TranscriptPanel } from './TranscriptPanel'

const STATEMENTS = [
  { text: 'Hi, I want to buy groceries.', start: 5.2, end: 6.94 },
  { text: 'Start a live Bajicam session.', start: 7.54, end: 9.02 },
]

describe('TranscriptPanel', () => {
  it('lists statements with their times, lighting the one playing', () => {
    render(<TranscriptPanel statements={STATEMENTS} currentTime={8} onSeek={() => {}} onEdit={() => {}} />)
    expect(screen.getByText('0:05')).toBeInTheDocument()
    expect(screen.getByText('Start a live Bajicam session.').parentElement?.className).toMatch(/rowCurrent/)
  })

  it('jumps to a statement from its time', async () => {
    const onSeek = vi.fn()
    render(<TranscriptPanel statements={STATEMENTS} currentTime={0} onSeek={onSeek} onEdit={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go to 0:07' }))
    expect(onSeek).toHaveBeenCalledWith(STATEMENTS[1])
  })

  it('rewrites a statement and previews the change', async () => {
    const onEdit = vi.fn()
    render(<TranscriptPanel statements={STATEMENTS} currentTime={0} onSeek={() => {}} onEdit={onEdit} />)
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await userEvent.clear(box)
    await userEvent.type(box, 'Start a Bhaji Cam session now.')
    await userEvent.click(screen.getByRole('button', { name: /preview change/i }))
    expect(onEdit).toHaveBeenCalledWith(STATEMENTS[1], 'Start a Bhaji Cam session now.')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('does not preview an unchanged statement', async () => {
    render(<TranscriptPanel statements={STATEMENTS} currentTime={0} onSeek={() => {}} onEdit={() => {}} />)
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    expect(screen.getByRole('button', { name: /preview change/i })).toBeDisabled()
  })

  it('cancels with Escape', async () => {
    const onEdit = vi.fn()
    render(<TranscriptPanel statements={STATEMENTS} currentTime={0} onSeek={() => {}} onEdit={onEdit} />)
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(onEdit).not.toHaveBeenCalled()
  })
})
