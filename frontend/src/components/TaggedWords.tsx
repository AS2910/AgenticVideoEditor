import type { ReactNode } from 'react'
import { splitTags } from '../transcript/tags'

/** A line's words with its audio tags taken out, the tags shown as quiet
 *  delivery chips beside it ("curious"), never as words. `wrap` styles the
 *  words (an <ins> on a proposal). */
export function TaggedWords({ text, className, wrap }: { text: string; className?: string; wrap?: (words: string) => ReactNode }) {
  const { words, tags } = splitTags(text)
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className={className}>{wrap ? wrap(words) : words}</span>
      {tags.map((t) => (
        <span key={t} className="tag rounded-[4px] border border-line2 px-1.5 py-px text-muted-foreground" data-testid="delivery-chip" title={`Said ${t}`}>
          {t}
        </span>
      ))}
    </span>
  )
}
