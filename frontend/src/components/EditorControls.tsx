import type { ComponentProps, ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** The small pieces LineDoc's editor and PlaceEditor share: a labelled row of
 *  controls, a choice chip (a button that is pressed or not), a native select
 *  and a text-link button. Native elements on purpose: a chip stays a button
 *  with aria-pressed, a select stays a combobox. */

/** One labelled row of the editor: "Delivery", "Voice", "If it runs long". */
export function ControlRow({ label, children, className, ...rest }: { label: string; children: ReactNode } & ComponentProps<'div'>) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2 text-sm text-muted-foreground', className)} {...rest}>
      <span className="w-32 min-w-0 shrink-0 whitespace-nowrap max-sm:w-full">{label}</span>
      {children}
    </div>
  )
}

/** A choice among a few: pressed means chosen. */
export function Chip({ on, className, ...props }: { on: boolean } & Omit<ComponentProps<typeof Button>, 'variant' | 'size'>) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-pressed={on}
      className={cn(
        'rounded-full',
        on && 'border-primary bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground dark:border-primary dark:bg-primary dark:hover:bg-primary/90',
        className,
      )}
      {...props}
    />
  )
}

/** Text that acts like a link: "in your words…", "Move", "Undo". */
export function LinkButton({ className, ...props }: Omit<ComponentProps<typeof Button>, 'variant' | 'size'>) {
  return <Button type="button" variant="link" size="sm" className={cn('h-auto min-h-0 px-1 py-1 text-sm pointer-coarse:min-h-11', className)} {...props} />
}
