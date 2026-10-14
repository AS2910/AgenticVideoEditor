import { cn } from '@/lib/utils'

/** Class strings the line editor and the voice-over editor share. */
export const selectClass = cn(
  'h-9 max-w-56 min-w-0 rounded-md border border-input bg-transparent px-2 text-sm text-foreground shadow-xs outline-none transition-[color,box-shadow] pointer-coarse:h-11',
  'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30',
  '[&>option]:bg-popover [&>option]:text-popover-foreground',
)

/** A rise-in for blocks that appear under a line (reduced-motion is zeroed globally). */
export const riseClass = 'animate-in fade-in-0 slide-in-from-top-1 duration-200'

/** The editor card that holds a line's or a voice-over's controls. */
export const editorClass = cn('flex flex-col gap-3 rounded-lg border bg-card p-3 text-card-foreground shadow-sm', riseClass)
