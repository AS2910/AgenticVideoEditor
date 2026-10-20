import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Toast } from '../jobs/model'

interface ToasterProps {
  toast: Toast | null
  onAction: (toast: Toast) => void
  onDismiss: () => void
}

/** One toast at a time (2026-10-20), bottom left, above the pane's composer
 *  line: render ready, a job failed, the turn finished. It leaves on its own
 *  (longer when it has a button) and waits while hovered or focused. */
export function Toaster({ toast, onAction, onDismiss }: ToasterProps) {
  const held = useRef(false)
  const dismiss = useRef(onDismiss)
  dismiss.current = onDismiss
  useEffect(() => {
    if (!toast) return
    let timer = 0
    // While the pointer or focus is on it, it waits; then it leaves.
    const arm = (ms: number) => { timer = window.setTimeout(() => (held.current ? arm(1500) : dismiss.current()), ms) }
    arm(toast.action ? 9000 : 5000)
    return () => window.clearTimeout(timer)
  }, [toast])
  if (!toast) return null
  return (
    <div
      className={cn('rise fixed bottom-5 left-5 z-40 flex max-w-[min(440px,calc(100vw-2.5rem))] items-center gap-3 rounded-xl border-[1.5px] border-ink px-4 py-3 shadow-volt', toast.tone === 'fail' ? 'bg-warn text-ink' : 'bg-ink text-ptext')}
      role={toast.tone === 'fail' ? 'alert' : 'status'}
      data-testid="toast"
      onMouseEnter={() => { held.current = true }} onMouseLeave={() => { held.current = false }}
      onFocus={() => { held.current = true }} onBlur={() => { held.current = false }}
    >
      <span className="min-w-0 flex-1 text-sm">{toast.text}</span>
      {toast.action && (
        <button type="button" className={cn('btn sm shrink-0', toast.tone === 'fail' ? '' : 'volt')} onClick={() => onAction(toast)}>{toast.action.label}</button>
      )}
      <button type="button" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md opacity-80 hover:opacity-100 focus-visible:outline-2 pointer-coarse:size-11" aria-label="Dismiss" onClick={onDismiss}><X size={14} aria-hidden="true" /></button>
    </div>
  )
}
