import { useEffect, useState } from 'react'
import type { Autonomy, Effort } from '../types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export interface MayDo {
  autonomy: Autonomy
  /** What one turn may spend, in dollars. */
  turn_usd: number
  effort: Effort
  /** The project's ceiling, read-only here. */
  ceiling_usd: number
}

const MODES: { value: Autonomy; label: string; help: string }[] = [
  { value: 'ask', label: 'Check with me', help: 'A paid or committing step waits for your yes.' },
  { value: 'draft', label: 'Just do it', help: 'Voltage voices and keeps going; it still says what it spent.' },
]
const EFFORTS: { value: Effort; label: string; help: string }[] = [
  { value: 'medium', label: 'Quick', help: 'Less thinking, cheaper turns.' },
  { value: 'high', label: 'Careful', help: 'The usual.' },
  { value: 'xhigh', label: 'Thorough', help: 'For a hard clip; slower and dearer.' },
]

/** "What Voltage may do" (20d): a real modal off the autonomy switch — the
 *  autonomy, what one turn may spend, and how hard Voltage thinks. Each
 *  choice saves on change; there is no Save button. */
export function WhatVoltageMayDo({ open, value, onChange, onClose }: {
  open: boolean
  value: MayDo
  onChange: (change: Partial<Pick<MayDo, 'autonomy' | 'turn_usd' | 'effort'>>) => void
  onClose: () => void
}) {
  const [cap, setCap] = useState(value.turn_usd.toFixed(2))
  useEffect(() => { setCap(value.turn_usd.toFixed(2)) }, [value.turn_usd])
  const commitCap = () => {
    const n = Number(cap)
    if (!Number.isFinite(n)) return setCap(value.turn_usd.toFixed(2))
    const bounded = Math.min(value.ceiling_usd, Math.max(0.01, Math.round(n * 100) / 100))
    setCap(bounded.toFixed(2))
    if (bounded !== value.turn_usd) onChange({ turn_usd: bounded })
  }
  const chip = (on: boolean) => cn('rounded-full', on && 'border-changed/40 bg-changed-soft text-changed hover:bg-changed-soft hover:text-changed dark:border-changed/40 dark:bg-changed-soft dark:hover:bg-changed-soft')
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-md" data-testid="may-do">
        <DialogTitle>What Voltage may do</DialogTitle>
        <DialogDescription>On this project. Each choice is saved as you make it.</DialogDescription>
        <div className="flex flex-col gap-5 text-sm">
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium">On its own</legend>
            <div className="flex flex-wrap gap-2" role="group" aria-label="How much Voltage does on its own">
              {MODES.map((m) => (
                <Button key={m.value} type="button" variant="outline" size="sm" className={chip(value.autonomy === m.value)} aria-pressed={value.autonomy === m.value} onClick={() => value.autonomy !== m.value && onChange({ autonomy: m.value })}>{m.label}</Button>
              ))}
            </div>
            <p className="m-0 text-muted-foreground">{MODES.find((m) => m.value === value.autonomy)?.help}</p>
          </fieldset>
          <div className="flex flex-col gap-2">
            <Label htmlFor="turn-cap">One turn may spend</Label>
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="text-muted-foreground">$</span>
              <Input id="turn-cap" type="number" inputMode="decimal" min={0.01} max={value.ceiling_usd} step={0.05} className="tnum w-28" value={cap}
                onChange={(e) => setCap(e.target.value)} onBlur={commitCap} onKeyDown={(e) => { if (e.key === 'Enter') commitCap() }} />
              <span className="text-muted-foreground">of a <span className="tnum">${value.ceiling_usd.toFixed(2)}</span> ceiling for the project</span>
            </div>
            <p className="m-0 text-muted-foreground">Voice and Claude together. Past it, Voltage asks instead of guessing.</p>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium">How hard it thinks</legend>
            <div className="flex flex-wrap gap-2" role="group" aria-label="How hard Voltage thinks">
              {EFFORTS.map((e) => (
                <Button key={e.value} type="button" variant="outline" size="sm" className={chip(value.effort === e.value)} aria-pressed={value.effort === e.value} onClick={() => value.effort !== e.value && onChange({ effort: e.value })}>{e.label}</Button>
              ))}
            </div>
            <p className="m-0 text-muted-foreground">{EFFORTS.find((e) => e.value === value.effort)?.help}</p>
          </fieldset>
        </div>
      </DialogContent>
    </Dialog>
  )
}
