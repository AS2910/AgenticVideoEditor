import type { ReactNode } from 'react'

/** The little markdown Voltage's replies use, parsed into blocks and inline
 *  marks and drawn as React nodes — never
 *  as HTML, so nothing a model writes can reach the page as markup.
 *
 *  Blocks: paragraphs (a blank line apart), bullet lists (`- ` / `* `),
 *  numbered lists (`1. `), headings (`#`…, shown as a bold line — a chat has
 *  no headings). Inline: **bold**, *italic* / _italic_, `code`, and
 *  [links](https://…) to http(s) only. A single newline is a line break.
 *  Plain text comes through as one text node, so tests that look for a
 *  sentence still find it. */

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'h'; text: string }

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

export function parse(text: string): Block[] {
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', lines: para })
    para = []
  }
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (line.trim() === '') { flush(); continue }
    const h = HEADING.exec(line)
    if (h) { flush(); blocks.push({ kind: 'h', text: h[1] }); continue }
    const b = BULLET.exec(line)
    const n = b ? null : NUMBERED.exec(line)
    if (b || n) {
      flush()
      const kind = b ? 'ul' : 'ol'
      const last = blocks[blocks.length - 1]
      const item = (b ?? n)![1]
      if (last && last.kind === kind) last.items.push(item)
      else blocks.push({ kind, items: [item] })
      continue
    }
    para.push(line)
  }
  flush()
  return blocks
}

// Inline marks, in the order they are tried at each position.
const INLINE = /(\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_]))/

const LINE_REF = /\b([Ll]ine) (\d{1,3})\b/g

/** "line 3" as a link to that row of the transcript (2026-10-20); the editor listens for it. */
function lineRefs(text: string, key: number): ReactNode {
  const parts: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(LINE_REF)) {
    const at = m.index ?? 0
    if (at > last) parts.push(text.slice(last, at))
    parts.push(<button key={`l${key}-${at}`} type="button" className="lineref" data-goto-line={m[2]} title={`Show line ${m[2]} in the transcript`}>{m[0]}</button>)
    last = at + m[0].length
  }
  if (!parts.length) return text
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export function inline(text: string, key = 0): ReactNode {
  const m = INLINE.exec(text)
  if (!m) return lineRefs(text, key)
  const before = text.slice(0, m.index)
  const after = text.slice(m.index + m[0].length)
  let node: ReactNode
  if (m[2] !== undefined || m[3] !== undefined) node = <strong key={key} className="font-semibold">{inline(m[2] ?? m[3], key + 1)}</strong>
  else if (m[4] !== undefined) node = <code key={key} className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[0.9em]">{m[4]}</code>
  else if (m[5] !== undefined) node = <a key={key} href={m[6]} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{inline(m[5], key + 1)}</a>
  else node = <em key={key}>{inline(m[7] ?? m[8], key + 1)}</em>
  if (!before && !after) return node
  return [before ? lineRefs(before, key + 500) : null, node, after ? inline(after, key + 1000) : null]
}

export const withBreaks = (lines: string[]): ReactNode =>
  lines.length === 1 ? inline(lines[0]) : lines.flatMap((l, i) => (i ? [<br key={`b${i}`} />, <span key={i}>{inline(l)}</span>] : [<span key={i}>{inline(l)}</span>]))
