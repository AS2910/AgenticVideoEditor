import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { LEARN_MORE } from './copy'

/** Voice consent V1 step 8: "Learn more", to Help's Using voices responsibly, in a new tab
 *  (the dialog and what was ticked stay put). Says so to a screen reader. */
export function LearnMore({ className }: { className?: string }) {
  return (
    <a href={hrefFor({ page: 'help', slug: LEARN_MORE.slug })} target="_blank" rel="noreferrer" data-testid="consent-learn-more"
      aria-label={`${LEARN_MORE.text} about using voices responsibly (opens in a new tab)`}
      className={cn('underline underline-offset-2 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 rounded-sm', className)}>
      {LEARN_MORE.text}
    </a>
  )
}
