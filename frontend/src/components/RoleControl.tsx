import { useId, useState } from 'react'
import type { MixLine, Role } from '../types'
import type { RoleChange, RoleQuestion } from '../api'
import { cn } from '@/lib/utils'
import { db, roleFacts } from '../transcript/roleFacts'

/** 2026-10-20: what an added line is in the mix. Its level follows from the
 *  role, measured against the clip's own speech: Voice (words), Bed (music,
 *  a crowd, ambience: under the voices, ducking while they speak), Effect.
 *  One line of facts says how it sits; Fine-tune nudges it -24 to +6 dB. The
 *  only speech in its span asks before it becomes a Bed. */
export interface RoleControlProps {
  role: Role
  offset: number
  /** What the last render measured for this line, if it has been rendered. */
  mix?: MixLine | null
  /** The bed setting, for the facts before anything is measured. */
  bedUnderDb?: number
  disabled?: boolean
  /** Apply a change; resolves to the server's question when it asks one first. */
  onChange: (change: RoleChange) => Promise<RoleQuestion | null | void>
  /** Play the line in place, in the version playing now. */
  onHear: () => void
}

const ROLES: { role: Role; label: string }[] = [
  { role: 'voice', label: 'Voice' }, { role: 'bed', label: 'Bed' }, { role: 'effect', label: 'Effect' },
]
export function RoleControl({ role, offset, mix, bedUnderDb = 15, disabled, onChange, onHear }: RoleControlProps) {
  const id = useId()
  const [tuning, setTuning] = useState(false)
  const [value, setValue] = useState(offset)
  const [question, setQuestion] = useState<RoleQuestion | null>(null)
  const [busy, setBusy] = useState(false)
  const apply = async (change: RoleChange) => {
    setBusy(true)
    try {
      const asked = await onChange(change)
      setQuestion(asked || null)
    } finally {
      setBusy(false)
    }
  }
  const commit = () => { if (Math.round(value) !== Math.round(offset)) void apply({ role, offset_db: Math.round(value) }) }
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="role">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex gap-1.5" role="group" aria-label="What this line is in the mix">
          {ROLES.map((r) => (
            <button key={r.role} type="button" className="pill h-8 px-3 pointer-coarse:h-11" aria-pressed={role === r.role}
              disabled={disabled || busy} onClick={() => { if (r.role !== role) void apply({ role: r.role, offset_db: 0 }) }}>
              {r.label}
            </button>
          ))}
        </span>
        <button type="button" className="act" aria-expanded={tuning} aria-controls={`${id}-tune`} onClick={() => { setValue(offset); setTuning((t) => !t) }}>
          Fine-tune
        </button>
      </div>
      <div className="meta" data-testid="role-facts">{roleFacts(role, offset, mix, bedUnderDb)}</div>
      {mix?.flag && <div className="meta text-needs" role="status" data-testid="mix-flag">{mix.flag}</div>}
      {tuning && (
        <div id={`${id}-tune`} className="flex flex-wrap items-center gap-3">
          <label className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground" htmlFor={`${id}-range`}>
            Fine-tune
          </label>
          <input
            id={`${id}-range`} type="range" min={-24} max={6} step={1} value={value}
            className="h-11 w-40 max-w-full accent-[var(--ink)]"
            aria-valuetext={db(value)} disabled={disabled || busy}
            onChange={(e) => setValue(Number(e.target.value))}
            onPointerUp={commit} onKeyUp={(e) => { if (e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End' || e.key.startsWith('Page')) commit() }}
          />
          <span className={cn('tnum w-14 text-sm', value !== 0 && 'text-foreground')} aria-hidden="true">{db(value)}</span>
          <button type="button" className="act" onClick={onHear}>Hear it in place</button>
        </div>
      )}
      {question && (
        <div className="waiting flex flex-col gap-2 rounded-[10px] px-3.5 py-3" role="group" aria-label="Before it becomes a Bed" data-testid="role-question">
          <span className="text-sm">{question.question}</span>
          <span className="flex flex-col gap-2">
            {question.options.map((o, k) => (
              <button key={o.label} type="button" className={cn('btn sm h-auto min-h-8 justify-start whitespace-normal py-1.5 text-left', k === 0 && 'volt')}
                disabled={busy} onClick={() => (o.role === role && o.offset_db === offset && !o.confirm ? setQuestion(null) : void apply({ role: o.role, offset_db: o.offset_db, confirm: o.confirm }))}>
                <span>{o.label}{o.detail && <span className="meta ml-1.5">{o.detail}</span>}</span>
              </button>
            ))}
          </span>
        </div>
      )}
    </div>
  )
}
