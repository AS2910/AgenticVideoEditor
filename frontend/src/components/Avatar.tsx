import { cn } from '@/lib/utils'

const initial = (name: string) => (name.replace(/^Speaker\s+/i, '').trim()[0] ?? '?').toUpperCase()

// Each slot is a speaker colour; an unknown slot falls back to a neutral.
const SLOT: Record<string, string> = {
  a: 'bg-spk-a',
  b: 'bg-spk-b',
  c: 'bg-spk-c',
  d: 'bg-spk-d',
}

/** A speaker's mark: their initial in their colour. */
export function Avatar({ name, slot, size = 22 }: { name: string; slot: string; size?: number }) {
  return (
    <span
      className={cn('inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-background', SLOT[slot] ?? 'bg-muted-foreground')}
      data-slot={slot}
      role="img"
      aria-label={name}
      title={name}
      style={{ width: size, height: size, fontSize: Math.max(12, Math.round(size * 0.5)) }}
    >
      {initial(name)}
    </span>
  )
}
