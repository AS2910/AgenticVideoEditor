import { cn } from '@/lib/utils'
import { parse, withBreaks, inline } from '@/lib/markdown'

interface MarkdownProps {
  text: string
  className?: string
  /** `span` keeps the words inline (one sentence inside another element). */
  as?: 'div' | 'span'
}

/** Voltage's words with their marks drawn: paragraphs, lists, bold, code. */
export function Markdown({ text, className, as = 'div' }: MarkdownProps) {
  const blocks = parse(text)
  // One plain paragraph stays one text node, with no wrapper of its own.
  if (blocks.length === 1 && blocks[0].kind === 'p') {
    const Tag = as
    return <Tag className={className}>{withBreaks(blocks[0].lines)}</Tag>
  }
  const Tag = as
  return (
    <Tag className={cn('flex flex-col gap-2', className)}>
      {blocks.map((b, i) => {
        if (b.kind === 'p') return <p key={i} className="m-0">{withBreaks(b.lines)}</p>
        if (b.kind === 'h') return <p key={i} className="m-0 font-semibold">{inline(b.text)}</p>
        const List = b.kind
        return (
          <List key={i} className={cn('m-0 flex flex-col gap-1 pl-5', b.kind === 'ul' ? 'list-disc' : 'list-decimal')}>
            {b.items.map((it, k) => <li key={k} className="pl-0.5">{inline(it)}</li>)}
          </List>
        )
      })}
    </Tag>
  )
}
