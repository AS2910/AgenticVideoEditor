import type { PlanItem } from '../types'
import { shortenUsd } from '../transcript/fit'

interface FitBannerProps {
  items: PlanItem[]
  disabled?: boolean
  onShortenAll: (items: PlanItem[]) => void
  onEaseAll?: (items: PlanItem[]) => void | Promise<unknown>
  onDiscardAll: (items: PlanItem[]) => void | Promise<unknown>
}

/** Several lines that ran long for the same reason, said once above them
 *  (p61): one sentence and three actions for all of them. */
export function FitBanner({ items, disabled, onShortenAll, onEaseAll, onDiscardAll }: FitBannerProps) {
  const easable = items.filter((i) => i.fit_failure?.eased_candidate_id)
  const usd = shortenUsd(items)
  return (
    <div className="waiting flex flex-col gap-2 rounded-[10px] px-3.5 py-3" role="status" data-testid="fit-banner">
      <span className="font-semibold">{items.length} lines are too long for their gaps.</span>
      <span className="-ml-2 flex flex-wrap items-center gap-1">
        <button type="button" className="btn sm" onClick={() => onShortenAll(items)} disabled={disabled}>
          Shorten all and voice{usd > 0 ? ` (~$${usd.toFixed(2)})` : ''}
        </button>
        {onEaseAll && easable.length > 0 && (
          <button type="button" className="act" onClick={() => void onEaseAll(easable)} disabled={disabled}
            title={easable.length === items.length ? 'Uses the takes already voiced; nothing is paid'
              : `Uses the takes already voiced for ${easable.length} of them; nothing is paid`}>
            Let the picture ease
          </button>
        )}
        <button type="button" className="act" onClick={() => void onDiscardAll(items)} disabled={disabled}>Discard all</button>
      </span>
    </div>
  )
}
