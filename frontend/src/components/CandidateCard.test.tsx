import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CandidateCard } from './CandidateCard'
import type { Candidate } from '../types'

const PASSING: Candidate = {
  candidate_id: 'c1',
  plan: { selection: { start: 0.4, end: 1.3 }, new_text: '30% off', voice_profile_id: 'speaker-1' },
  audio: { kind: 'audio', sha256: 'a'.repeat(64), duration: 0.9, container: 'wav' },
  frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 0.9, container: 'mp4' },
  continuity: {
    voice_match: 0.95, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94,
    passed: true, warnings: [],
  },
}

const FAILING: Candidate = {
  ...PASSING,
  continuity: {
    voice_match: 0.4, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94,
    passed: false, warnings: ['Low voice identity (0.40)'],
  },
}

describe('CandidateCard', () => {
  it('reports the real generated media backing the candidate', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} />)
    const media = screen.getByTestId('candidate-media')
    expect(media).toHaveTextContent('0.90s generated')
    expect(media).toHaveTextContent('WAV + MP4')
  })

  it('shows the new text, the pass badge, and all four metrics', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} />)
    expect(screen.getByText('30% off')).toBeInTheDocument()
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()
    expect(screen.getByText(/voice identity/i)).toBeInTheDocument()
    expect(screen.getByText(/prosody/i)).toBeInTheDocument()
    expect(screen.getByText(/audio integration/i)).toBeInTheDocument()
    expect(screen.getByText(/lip-sync/i)).toBeInTheDocument()
  })

  it('renders the four scores to two decimal places', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} />)
    for (const v of ['0.95', '0.92', '0.97', '0.94']) {
      expect(screen.getByText(v)).toBeInTheDocument()
    }
  })

  it('fires onApprove when passing and Approve is clicked', async () => {
    const onApprove = vi.fn()
    render(<CandidateCard candidate={PASSING} onApprove={onApprove} onTryAgain={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('fires onTryAgain when Try again is clicked', async () => {
    const onTryAgain = vi.fn()
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={onTryAgain} />)
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(onTryAgain).toHaveBeenCalledOnce()
  })

  it('disables Approve and surfaces warnings when continuity fails', () => {
    render(<CandidateCard candidate={FAILING} onApprove={() => {}} onTryAgain={() => {}} />)
    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByText(/low voice identity/i)).toBeInTheDocument()
    expect(screen.getByText(/below threshold/i)).toBeInTheDocument()
    expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument()
  })

  it('marks only the below-threshold metric as warning', () => {
    render(<CandidateCard candidate={FAILING} onApprove={() => {}} onTryAgain={() => {}} />)
    const bars = screen.getAllByTestId('metric-bar')
    expect(bars).toHaveLength(4)
    const warned = bars.filter((b) => b.getAttribute('data-ok') === 'false')
    expect(warned).toHaveLength(1)
  })
})
