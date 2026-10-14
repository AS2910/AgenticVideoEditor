import { useState } from 'react'
import type { Usage } from '../types'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

const VENDORS: Record<string, string> = {
  openai: 'Transcription', elevenlabs: 'Voice', anthropic: 'Reading requests',
}

/** The project's spend against its cap, as a small meter (UX-3). The meter is
 *  a button: its breakdown — each vendor's line, voice characters against
 *  their ceiling, and with sign-in on the person's spend across projects —
 *  opens as a popover, so it is there for touch and keyboard, not only under
 *  a hover. Escape or a click outside closes it and focus returns to the
 *  meter (Radix does both). */
export function SpendMeter({ usage }: { usage: Usage | null }) {
  const [open, setOpen] = useState(false)
  if (!usage) return null
  const share = usage.ceiling_usd > 0 ? Math.min(1, usage.spent_usd / usage.ceiling_usd) : 0
  const near = share >= 0.8
  const spent = `$${usage.spent_usd.toFixed(2)} of $${usage.ceiling_usd.toFixed(2)}`
  const across = usage.user_spent_usd != null && usage.user_ceiling_usd != null
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className={cn('text-muted-foreground', near && 'text-needs')}
          data-testid="spend"
          aria-controls={open ? 'spend-breakdown' : undefined}
          aria-label={`Spent ${spent} on this project${near ? ', near the cap' : ''}. ${open ? 'Hide' : 'Show'} the breakdown`}
        >
          <span className="tnum">{spent}</span>
          {near && <span className="font-medium" role="status">near the cap</span>}
          <span
            className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-muted md:inline-block"
            role="meter"
            aria-label="Spend against the cap"
            aria-valuemin={0}
            aria-valuemax={usage.ceiling_usd}
            aria-valuenow={usage.spent_usd}
          >
            <span
              className={cn('block h-full w-full origin-left rounded-full bg-primary', near && 'bg-needs')}
              style={{ transform: `scaleX(${share})` }}
            />
          </span>
          {' '}
          <span className="hidden xl:inline">{usage.voice_characters.toLocaleString()} of {usage.voice_characters_ceiling.toLocaleString()} voice characters</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent id="spend-breakdown" align="end" className="w-72" aria-label="Spend breakdown" data-testid="spend-breakdown">
        <dl className="m-0 flex flex-col gap-1.5 text-sm">
          {usage.lines.map((l) => (
            <div key={`${l.vendor}-${l.what}-${l.unit}`} className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{VENDORS[l.vendor] ?? l.vendor}</dt>
              <dd className="tnum m-0 whitespace-nowrap">${l.usd.toFixed(3)} <span className="text-muted-foreground">· {l.calls} {l.calls === 1 ? 'call' : 'calls'}</span></dd>
            </div>
          ))}
          {usage.lines.length === 0 && (
            <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Nothing spent yet</dt><dd className="tnum m-0">$0.000</dd></div>
          )}
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Voice characters</dt>
            <dd className="tnum m-0 whitespace-nowrap">{usage.voice_characters.toLocaleString()} <span className="text-muted-foreground">of {usage.voice_characters_ceiling.toLocaleString()}</span></dd>
          </div>
          {across && (
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">You, across projects</dt>
              <dd className="tnum m-0 whitespace-nowrap">${usage.user_spent_usd!.toFixed(2)} <span className="text-muted-foreground">of ${usage.user_ceiling_usd!.toFixed(2)}</span></dd>
            </div>
          )}
        </dl>
      </PopoverContent>
    </Popover>
  )
}
