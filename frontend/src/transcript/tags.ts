/** Audio tags in a line's words ("[curious] So…"): the model performs them,
 *  nobody reads them. A row shows the words without them and the tags as
 *  delivery chips beside the line. */
const TAG = /\[([^[\]\n]{1,40})\]/g

export interface Tagged {
  words: string
  tags: string[]
}

export function splitTags(text: string): Tagged {
  const tags: string[] = []
  const words = (text ?? '').replace(TAG, (_m, tag: string) => {
    const t = tag.trim()
    if (t && !tags.includes(t)) tags.push(t)
    return ' '
  })
  return { words: words.replace(/\s+/g, ' ').trim(), tags }
}
