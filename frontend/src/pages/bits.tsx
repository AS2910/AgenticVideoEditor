import { useState } from 'react'
import type { ReactNode } from 'react'
import { frameUrl } from '../api'
import { cn } from '@/lib/utils'

/** The video's first frame; a plain dark block when there is none to fetch (project page cards and board). */
export function Frame({ id }: { id: string }) {
  const [broken, setBroken] = useState(false)
  if (broken) return <span className="absolute inset-0 block bg-pic" aria-hidden="true" />
  return <img className="absolute inset-0 size-full object-cover" src={frameUrl(id, 0)} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />
}

/** A volt fill in an outlined track — the spend bars. `strong` is the 1.5 px ink outline of the big ones. */
export function FillBar({ share, height = 10, strong = false, label, className }: {
  share: number; height?: number; strong?: boolean; label?: string; className?: string
}) {
  const pct = Math.max(0, Math.min(1, Number.isFinite(share) ? share : 0))
  const a11y = label ? { role: 'meter', 'aria-label': label, 'aria-valuenow': Math.round(pct * 100), 'aria-valuemin': 0, 'aria-valuemax': 100 } : { 'aria-hidden': true as const }
  return (
    <span {...a11y} className={cn('block overflow-hidden', strong ? 'rounded border-[1.5px] border-foreground' : 'rounded-[3px] border border-line2 bg-sunk', className)} style={{ height }}>
      <span className={cn('fillin block h-full bg-volt', pct > 0 && 'border-r-[1.5px] border-ink')} style={{ width: `${pct * 100}%` }} />
    </span>
  )
}

/** A number with its tag over it. */
export function Tile({ label, value, tone = 'card', size = 'lg', className }: {
  label: string; value: ReactNode; tone?: 'card' | 'ink' | 'volt'; size?: 'lg' | 'md'; className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-0.5 rounded-[10px] border-[1.5px] p-4', tone === 'card' && 'border-foreground bg-card', tone === 'ink' && 'border-ink bg-ink text-volt', tone === 'volt' && 'border-ink bg-volt text-ink', className)}>
      <div className={cn('tag', tone === 'card' && 'text-faint')}>{label}</div>
      <div className={cn('disp font-bold', size === 'lg' ? 'text-4xl' : 'text-[28px]')}>{value}</div>
    </div>
  )
}
