import { Loader2, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Voltage's presence beside its words: a bolt, or a spinner while it works.
 *  (UX-8 replaced the glowing orb with this.) */
export function Presence({ size = 16, working = false, className }: { size?: number; working?: boolean; className?: string }) {
  const Icon = working ? Loader2 : Zap
  return (
    <Icon
      aria-hidden="true"
      width={size}
      height={size}
      className={cn('shrink-0 text-changed', working && 'animate-spin', className)}
    />
  )
}
