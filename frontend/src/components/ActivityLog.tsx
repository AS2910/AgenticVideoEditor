import type { Plan } from '../types'
import { Presence } from './Presence'

/** Seconds since the plan was made, as m:ss. */
const since = (iso: string, from: string) => {
  const s = Math.max(0, Math.round((new Date(iso).getTime() - new Date(from).getTime()) / 1000))
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`
}

/** What Voltage did: the plan's log, oldest first. */
export function ActivityLog({ plan }: { plan: Plan }) {
  if (plan.log.length === 0) return null
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-4 text-card-foreground shadow-xs" data-testid="activity">
      <div className="flex items-center gap-2">
        <Presence size={16} />
        <h2 className="m-0 text-sm font-semibold">What I did</h2>
        <span className="flex-1" />
        {plan.spend_usd > 0 && <span className="tnum whitespace-nowrap text-xs text-muted-foreground">${plan.spend_usd.toFixed(2)} for this plan</span>}
      </div>
      {plan.log.map((e, i) => (
        <div key={i} className="flex gap-3 text-sm text-muted-foreground">
          <span className="tnum w-11 flex-none">{since(e.at, plan.created_at)}</span>
          <span className="flex-1 text-foreground">{e.text}</span>
          <span className="min-w-0 max-w-[40%] overflow-hidden text-ellipsis whitespace-nowrap">{e.detail}</span>
        </div>
      ))}
    </div>
  )
}
