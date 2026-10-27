import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { useOnboarding } from './onboarding'
import { useTipQueue } from './TipQueue'
import { tipById } from './tips'
import type { TipDef } from './tips'

/** A first-time tip: a black card with one Got it, which puts it away for good.
 *  Run 5 item 3: a tip no longer floats over the page under its control. It asks
 *  the tip queue, and when its turn comes it shows in the queue's slot (Voltage's
 *  pane in the editor, under the top bar elsewhere), in the flow, so it covers
 *  nothing and never moves while it is up. Renders nothing once met.
 *  `inline` (9e): the card sits where it is rendered, for a tip inside a modal,
 *  whose focus trap a card outside would sit behind. */
export function Tip({ id, className, inline = false }: { id: string; className?: string; inline?: boolean }) {
  const { onboarding, loaded, markTip } = useOnboarding()
  const queue = useTipQueue()
  const def = tipById(id)
  const wanted = loaded && !!def && !onboarding.tips.includes(id)
  const request = queue?.request
  useEffect(() => {
    if (!request || !wanted) return
    return request(id, inline)
  }, [request, wanted, id, inline])

  if (!wanted || !def) return null
  const card = <TipCard def={def} className={className} onDone={() => markTip(id)} />
  // Without a queue (a component on its own in a test) the tip sits where it is.
  if (!queue || inline) return !queue || queue.active === id ? card : null
  if (queue.active !== id || !queue.slot) return null
  return createPortal(card, queue.slot)
}

function TipCard({ def, className, onDone }: { def: TipDef; className?: string; onDone: () => void }) {
  return (
    <div
      role="status" aria-label={`Tip: ${def.title}`} data-tip={def.id}
      className={cn('relative flex w-full flex-col gap-2 rounded-xl border border-pline bg-ink p-4 text-ptext shadow-volt-lg', className)}
    >
      <span className="tag text-volt">{def.title}</span>
      <span className="text-[15px]">{def.text}</span>
      <div className="flex flex-wrap items-center gap-2">
        <a href={hrefFor({ page: 'help', slug: def.slug })} className="tag text-pmuted no-underline hover:text-ptext">{def.link} →</a>
        <span className="flex-1" />
        <button type="button" className="btn volt sm" onClick={onDone}>Got it</button>
      </div>
    </div>
  )
}
