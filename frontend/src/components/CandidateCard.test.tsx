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
    passed: true, warnings: [], measured: [],
  },
}

const FAILING: Candidate = {
  ...PASSING,
  continuity: {
    voice_match: 0.4, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94,
    passed: false, warnings: ['Low voice identity (0.40)'], measured: [],
  },
}

describe('CandidateCard', () => {
  it('reports the real generated media backing the candidate', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    const media = screen.getByTestId('candidate-media')
    expect(media).toHaveTextContent('0.90s generated')
    expect(media).toHaveTextContent('WAV + MP4')
  })

  it('plays the generated audio straight from the artifact store', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    const player = screen.getByTestId('candidate-audio')
    expect(player.tagName).toBe('AUDIO')
    expect(player).toHaveAttribute('src', `/api/projects/p1/artifacts/${'a'.repeat(64)}`)
    expect(player).toHaveAttribute('controls')
  })

  it('shows the stock-voice label the backend attaches', () => {
    const stock: Candidate = {
      ...PASSING,
      continuity: { ...PASSING.continuity, warnings: ["Stock voice — this is not the speaker's voice yet."] },
    }
    render(<CandidateCard candidate={stock} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    expect(screen.getByText(/not the speaker's voice/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve/i })).toBeEnabled()
  })

  it('says which scores were measured and which cannot be yet', () => {
    const measured: Candidate = {
      ...PASSING,
      continuity: {
        voice_match: null, prosody: 0.97, audio_integration: 0.99, lip_sync: null,
        passed: true, warnings: [], measured: ['prosody', 'audio_integration'],
      },
    }
    render(<CandidateCard candidate={measured} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    expect(screen.getAllByText(/not measured yet/i)).toHaveLength(2)
    expect(screen.getAllByTestId('metric-bar')).toHaveLength(2)
    expect(screen.getByText('0.97')).toBeInTheDocument()
    expect(screen.queryByText(/simulated/i)).not.toBeInTheDocument()
  })

  it('tags made-up mock scores as simulated', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    expect(screen.getAllByText(/simulated/i)).toHaveLength(4)
  })

  it('shows the new text, the pass badge, and all four metrics', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    expect(screen.getByText('30% off')).toBeInTheDocument()
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()
    expect(screen.getByText(/voice identity/i)).toBeInTheDocument()
    expect(screen.getByText(/prosody/i)).toBeInTheDocument()
    expect(screen.getByText(/audio integration/i)).toBeInTheDocument()
    expect(screen.getByText(/lip-sync/i)).toBeInTheDocument()
  })

  it('renders the four scores to two decimal places', () => {
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    for (const v of ['0.95', '0.92', '0.97', '0.94']) {
      expect(screen.getByText(v)).toBeInTheDocument()
    }
  })

  it('fires onApprove when passing and Approve is clicked', async () => {
    const onApprove = vi.fn()
    render(<CandidateCard candidate={PASSING} onApprove={onApprove} onTryAgain={() => {}} projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('fires onTryAgain when Try again is clicked', async () => {
    const onTryAgain = vi.fn()
    render(<CandidateCard candidate={PASSING} onApprove={() => {}} onTryAgain={onTryAgain} projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(onTryAgain).toHaveBeenCalledOnce()
  })

  it('disables Approve and surfaces warnings when continuity fails', () => {
    render(<CandidateCard candidate={FAILING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByText(/low voice identity/i)).toBeInTheDocument()
    expect(screen.getByText(/below threshold/i)).toBeInTheDocument()
    expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument()
  })

  it('marks only the below-threshold metric as warning', () => {
    render(<CandidateCard candidate={FAILING} onApprove={() => {}} onTryAgain={() => {}} projectId="p1" />)
    const bars = screen.getAllByTestId('metric-bar')
    expect(bars).toHaveLength(4)
    const warned = bars.filter((b) => b.getAttribute('data-ok') === 'false')
    expect(warned).toHaveLength(1)
  })

  it('offers Approve anyway when continuity fails, and reports it', async () => {
    const onApproveAnyway = vi.fn()
    render(
      <CandidateCard
        candidate={FAILING} onApprove={() => {}} onApproveAnyway={onApproveAnyway}
        onTryAgain={() => {}} projectId="p1"
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /approve anyway/i }))
    expect(onApproveAnyway).toHaveBeenCalledOnce()
  })

  it('never offers Approve anyway when continuity passed', () => {
    render(
      <CandidateCard
        candidate={PASSING} onApprove={() => {}} onApproveAnyway={() => {}}
        onTryAgain={() => {}} projectId="p1"
      />,
    )
    expect(screen.queryByRole('button', { name: /approve anyway/i })).not.toBeInTheDocument()
  })
})
