import type { PlanItem } from '../types'
import { Button } from '@/components/ui/button'

interface ShipCardProps {
  /** The lines voiced and not yet shipped. */
  ready: PlanItem[]
  /** Those of them the user is keeping (the rest are held as drafts). */
  kept: PlanItem[]
  /** The script is showing the review (each line's seam, Keep / Hold). */
  review: boolean
  onReview: () => void
  onShip: () => void | Promise<unknown>
  busy?: boolean
}

/** The panel's last element once lines are voiced (15e, from the rule that
 *  the user's next action is always last): what is ready, and Ship. Saying
 *  "ship it" in the composer does the same. */
export function ShipCard({ ready, kept, review, onReview, onShip, busy }: ShipCardProps) {
  const held = ready.length - kept.length
  const passed = ready.filter((i) => i.candidate?.continuity.passed).length
  const sub = held > 0 ? `Keeping ${kept.length}, holding ${held} as ${held === 1 ? 'a draft' : 'drafts'}.`
    : passed === ready.length ? `${ready.length === 1 ? 'It sounds' : 'All of them sound'} right.`
    : `${passed} of ${ready.length} sound right. Play each seam before you ship.`
  const label = kept.length === 0 ? 'Ship'
    : kept.length === ready.length ? `Ship ${kept.length} ${kept.length === 1 ? 'change' : 'changes'}`
    : `Ship ${kept.length} of ${ready.length}`
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-background p-4 shadow-xs" data-testid="next-action" role="group" aria-label="Ready to ship">
      <div className="text-chat">
        <span className="font-semibold">{ready.length === 1 ? 'One line is ready to ship.' : `${ready.length} lines are ready to ship.`}</span> {sub}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onReview} aria-pressed={review}>
          {review ? 'Back to the script' : 'Play the seams'}
        </Button>
        <span className="flex-1" />
        <Button type="button" size="sm" onClick={() => void onShip()} disabled={busy || kept.length === 0}>{label}</Button>
      </div>
      <div className="text-sm text-muted-foreground">Or just say “ship it”.</div>
    </div>
  )
}
