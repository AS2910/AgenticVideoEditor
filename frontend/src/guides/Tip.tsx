import { useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { useTargetBox } from '../tour/measure'
import { useOnboarding } from './onboarding'
import { tipById } from './tips'

const W = 320, EDGE = 16, GAP = 12

/** A first-time tip: a black card with a caret under the control named by
 *  `target` (bottom-right of the page when it is not there), shown once —
 *  Got it remembers it. Renders nothing when the person has met it. */
export function Tip({ id, target, className }: { id: string; target: string; className?: string }) {
  const { onboarding, loaded, markTip } = useOnboarding()
  const def = tipById(id)
  const show = loaded && !!def && !onboarding.tips.includes(id)
  const box = useTargetBox([target], show, 0)
  const card = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<CSSProperties & { caretX?: number }>({ right: EDGE, bottom: EDGE })

  useLayoutEffect(() => {
    if (!show) return
    const vw = window.innerWidth, vh = window.innerHeight
    const h = card.current?.offsetHeight ?? 150
    if (!box || vw < 640) { setPos({ right: EDGE, bottom: EDGE, left: vw < 640 ? EDGE : undefined }); return }
    const w = Math.min(W, vw - EDGE * 2)
    const left = Math.max(EDGE, Math.min(vw - w - EDGE, box.left))
    const below = box.top + box.height + GAP
    const caret = Math.max(16, Math.min(w - 32, box.left + box.width / 2 - left - 8))
    if (below + h <= vh - EDGE) setPos({ left, top: below, width: w, caretX: caret })
    else setPos({ left, top: Math.max(EDGE, box.top - GAP - h), width: w, caretX: -1 })
  }, [show, box])

  if (!show || !def) return null
  const { caretX, ...style } = pos
  const pointing = typeof caretX === 'number' && caretX >= 0
  return (
    <div
      ref={card} role="status" aria-label={`Tip: ${def.title}`} data-tip={id}
      className={cn('rise fixed z-40 flex max-w-[calc(100vw-32px)] flex-col gap-2 rounded-xl bg-ink p-4 text-ptext shadow-volt-lg', className)}
      style={{ width: W, ...style }}
    >
      {pointing && <span aria-hidden="true" className="absolute -top-2 size-4 rotate-45 rounded-sm bg-ink" style={{ left: caretX }} />}
      <span className="tag text-volt">{def.title}</span>
      <span className="text-[15px]">{def.text}</span>
      <div className="flex items-center gap-2">
        <a href={hrefFor({ page: 'help', slug: def.slug })} className="tag text-pmuted no-underline hover:text-ptext">{def.link} →</a>
        <span className="flex-1" />
        <button type="button" className="btn volt sm" onClick={() => markTip(id)}>Got it</button>
      </div>
    </div>
  )
}
