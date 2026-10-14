import { useState } from 'react'
import type { Candidate, ContinuityReport } from '../types'
import { artifactUrl } from '../api'
import { Avatar } from './Avatar'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// Fixed order, mirroring the backend's continuity engine.
const METRICS: { key: keyof ContinuityReport; label: string }[] = [
  { key: 'voice_match', label: 'Voice identity' },
  { key: 'prosody', label: 'Prosody & energy' },
  { key: 'audio_integration', label: 'Audio integration' },
  { key: 'lip_sync', label: 'Lip-sync' },
]

const THRESHOLD = 0.8

interface CandidateCardProps {
  candidate: Candidate
  onApprove: () => void | Promise<unknown>
  /** Approve despite failed continuity — offered only when it failed. */
  onApproveAnyway?: () => void | Promise<unknown>
  onTryAgain: () => void
  projectId: string
  /** Which change this is a take of, e.g. "The change at 0:07". */
  label?: string
  /** Who says it. */
  speaker?: { name: string; slot: string } | null
  /** How the line was placed, e.g. "Ran 0.4 s into the pause after it". */
  note?: string | null
}

/** A take: the new line, playable, and how well it sits. */
export function CandidateCard({
  candidate, onApprove, onApproveAnyway, onTryAgain, projectId, label, speaker, note,
}: CandidateCardProps) {
  const c = candidate.continuity
  const [pending, setPending] = useState(false)
  const run = async (fn: () => void | Promise<unknown>) => {
    setPending(true)
    try { await fn() } finally { setPending(false) }
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4 text-card-foreground shadow-xs" aria-busy={pending || undefined}>
      {(label || speaker || note) && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {speaker && <Avatar name={speaker.name} slot={speaker.slot} size={18} />}
          {label && <span className="min-w-0">{label}</span>}
          <span className="flex-1" />
          {note && <span data-testid="placement">{note}</span>}
        </div>
      )}
      <div className="text-base">{candidate.plan.new_text}</div>

      {/* The generated line, playable. The frames stay unplayed until lip-sync
          is real (Phase 5): today they are a flat colour. */}
      <audio
        data-testid="candidate-audio"
        className="h-11 w-full"
        controls
        preload="auto"
        src={artifactUrl(projectId, candidate.audio.sha256)}
      />

      <div className="tnum text-sm text-muted-foreground" data-testid="candidate-media">
        {candidate.frames.duration.toFixed(2)}s generated ·{' '}
        {candidate.audio.container.toUpperCase()} + {candidate.frames.container.toUpperCase()}
      </div>

      {c.passed ? (
        <div className="self-start text-sm font-medium text-ok">Continuity checked</div>
      ) : (
        <div className="self-start text-sm font-medium text-needs" role="status">Continuity below threshold</div>
      )}

      <div className="flex flex-col gap-1.5">
        {METRICS.map(({ key, label: name }) => {
          const value = c[key] as number | null
          if (value === null) {
            return (
              <div key={key} className="grid grid-cols-[8rem_1fr_2.25rem] items-center gap-2 text-sm">
                <span className="text-muted-foreground">{name}</span>
                <span className="col-span-2 text-muted-foreground">not measured yet</span>
              </div>
            )
          }
          const ok = value >= THRESHOLD
          const simulated = !c.measured.includes(key)
          return (
            <div key={key} className="grid grid-cols-[8rem_1fr_2.25rem] items-center gap-2 text-sm">
              <span className="text-muted-foreground">
                {name}
                {simulated && <span> · simulated</span>}
              </span>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  data-testid="metric-bar"
                  data-ok={ok}
                  className={cn('h-full w-full origin-left transition-transform duration-300', ok ? 'bg-ok' : 'bg-needs')}
                  style={{ transform: `scaleX(${Math.min(1, Math.max(0, value))})` }}
                />
              </div>
              <span className="tnum text-right">{value.toFixed(2)}</span>
              {!ok && <span className="sr-only">, below {THRESHOLD.toFixed(2)}</span>}
            </div>
          )
        })}
      </div>

      {c.warnings.length > 0 && (
        <ul className="m-0 list-disc pl-4 text-sm text-needs">
          {c.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      {!c.passed && (
        <div className="text-sm text-muted-foreground">
          {onApproveAnyway
            ? 'Below the threshold. Approve anyway keeps it for a trial; Try again makes another take.'
            : "Below the threshold, so it can't be approved as it is. Try again for another take."}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onTryAgain}>Try again</Button>
        {c.passed || !onApproveAnyway ? (
          <Button onClick={() => void run(onApprove)} disabled={!c.passed || pending} aria-busy={pending || undefined}>
            {pending ? 'Approving…' : 'Approve'}
          </Button>
        ) : (
          <Button variant="outline" className="border-needs text-needs hover:bg-needs-soft hover:text-needs" onClick={() => void run(onApproveAnyway)} disabled={pending} aria-busy={pending || undefined}>
            {pending ? 'Approving…' : 'Approve anyway'}
          </Button>
        )}
      </div>
    </div>
  )
}
