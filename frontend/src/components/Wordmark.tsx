import { cn } from '@/lib/utils'

/** The bolt in a volt square, and VOLTAGE in display type (Volt, 2026-10-18).
 *  A link to the start when `href` is given. */
export function Wordmark({ href = '#projects', size = 26, className, label = 'Voltage, all projects' }: { href?: string | null; size?: number; className?: string; label?: string }) {
  const inner = (
    <>
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
        <rect x=".75" y=".75" width="22.5" height="22.5" rx="6" className="fill-volt stroke-ink" strokeWidth="1.5" />
        <path d="M13.5 4 7 13h4.5l-1 7L17 11h-4.5z" className="fill-ink" />
      </svg>
      <span>VOLTAGE</span>
    </>
  )
  const classes = cn('disp inline-flex items-center gap-2.5 text-[17px] font-bold tracking-[.02em] text-foreground no-underline', className)
  return href ? <a href={href} aria-label={label} className={classes}>{inner}</a> : <span className={classes}>{inner}</span>
}

/** Voltage's presence (Volt): slow volt bars idle, fast while it works, amber when it needs you. */
export function Wave({ busy, need, bars = 5, className, height = 20 }: { busy?: boolean; need?: boolean; bars?: number; className?: string; height?: number }) {
  return (
    <span className={cn('wave', busy && 'busy', need && 'need', className)} aria-hidden="true" style={{ height }} data-testid="wave" data-state={need ? 'need' : busy ? 'busy' : 'idle'}>
      {Array.from({ length: bars }, (_, i) => <i key={i} style={{ height }} />)}
    </span>
  )
}
