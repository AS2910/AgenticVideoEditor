import type { Autonomy } from '../types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const MODES: { value: Autonomy; label: string }[] = [
  { value: 'ask', label: 'Check with me' },
  { value: 'draft', label: 'Just do it' },
]

/** How much Voltage does on its own. "Check with me" is the default: every
 *  plan waits for you to say go. */
export function AutonomySwitch({ value, onChange }: { value: Autonomy; onChange: (v: Autonomy) => void }) {
  return (
    <div className="flex gap-0.5 rounded-lg bg-muted p-0.5" role="group" aria-label="How much Voltage does on its own">
      {MODES.map((m) => (
        <Button
          key={m.value}
          variant="ghost"
          size="sm"
          className={cn(
            'text-muted-foreground',
            value === m.value && 'bg-background text-foreground shadow-xs hover:bg-background dark:bg-card dark:hover:bg-card',
          )}
          aria-pressed={value === m.value}
          onClick={() => onChange(m.value)}
        >
          {m.label}
        </Button>
      ))}
    </div>
  )
}
