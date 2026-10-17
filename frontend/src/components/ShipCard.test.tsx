import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ShipCard } from './ShipCard'
import type { PlanItem } from '../types'

const item = (id: string, passed = true): PlanItem => ({
  item_id: id, selection: { start: 1, end: 2 }, old_text: 'old', new_text: 'new', speaker: 'A', mix: 'replace',
  delivery: null, reason: '', kind: 'planned', enabled: true, status: 'ready', fit: null, edit_id: null,
  question: null, error: null, note: null, progress: null,
  candidate: { candidate_id: `c-${id}`, plan: { selection: { start: 1, end: 2 }, new_text: 'new', voice_profile_id: 'v' }, continuity: { passed, checks: [] } } as unknown as PlanItem['candidate'],
})

describe('ShipCard', () => {
  it('says what is ready, plays the seams, and ships the lines kept', async () => {
    const onShip = vi.fn()
    const onReview = vi.fn()
    render(<ShipCard ready={[item('a'), item('b')]} kept={[item('a')]} review={false} onReview={onReview} onShip={onShip} />)
    expect(screen.getByRole('group', { name: 'Ready to ship' })).toHaveTextContent('2 lines are ready to ship. Keeping 1, holding 1 as a draft.')
    await userEvent.click(screen.getByRole('button', { name: 'Play the seams' }))
    expect(onReview).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Ship 1 of 2' }))
    expect(onShip).toHaveBeenCalled()
    expect(screen.getByText('Or just say “ship it”.')).toBeInTheDocument()
  })

  it('asks for a listen when a seam failed its check, and cannot ship with nothing kept', () => {
    const { unmount } = render(<ShipCard ready={[item('a', false)]} kept={[item('a', false)]} review onReview={() => {}} onShip={() => {}} />)
    expect(screen.getByRole('group')).toHaveTextContent('One line is ready to ship. 0 of 1 sound right. Play each seam before you ship.')
    expect(screen.getByRole('button', { name: 'Back to the script' })).toHaveAttribute('aria-pressed', 'true')
    unmount()
    render(<ShipCard ready={[item('a', false)]} kept={[]} review={false} onReview={() => {}} onShip={() => {}} />)
    expect(screen.getByRole('group')).toHaveTextContent('Keeping 0, holding 1 as a draft.')
    expect(screen.getByRole('button', { name: 'Ship' })).toBeDisabled()
  })
})
