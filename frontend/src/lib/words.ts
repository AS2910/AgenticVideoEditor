const MAX_CHARS = 40
const MAX_WORDS = 4

/** The words of a selection as a term: one to four words, no line break, the
 *  punctuation around them dropped. Null when it is not a word to learn. */
export function termOf(text: string): string | null {
  if (/\n/.test(text)) return null
  const t = text.trim().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '')
  if (!t || t.length > MAX_CHARS || t.split(/\s+/).length > MAX_WORDS) return null
  return t
}
