import { diffWords } from './changes'

/** Run 5 item 6: the fast path for small edits. The server routes (POST
 *  /videos/{id}/lines/quick); this is the same rule, so the line editor can say
 *  beforehand which way an edit will go. */
export const MAX_QUICK_WORDS = 8

/** How many words an edit changes: for each changed run, the longer of what
 *  went and what came ("20%" to "30%" is 1). */
export function changedWords(before: string, after: string): number {
  let total = 0, del = 0, ins = 0
  const settle = () => { total += Math.max(del, ins); del = 0; ins = 0 }
  for (const run of diffWords(before, after)) {
    const n = run.text.split(/\s+/).filter(Boolean).length
    if (run.kind === 'same') settle()
    else if (run.kind === 'del') del += n
    else ins += n
  }
  settle()
  return total
}

export interface QuickRoute { fast: boolean; changed: number; reason: string }

/** Fast when one existing line changes by 1 to MAX_QUICK_WORDS words in its own voice. */
export function quickRoute(before: string, after: string, voiceChanged: boolean): QuickRoute {
  const changed = changedWords(before, after.trim())
  if (voiceChanged) return { fast: false, changed, reason: 'a different voice' }
  if (changed === 0) return { fast: false, changed, reason: 'no words changed' }
  if (changed > MAX_QUICK_WORDS) return { fast: false, changed, reason: `${changed} words changed` }
  return { fast: true, changed, reason: `${changed} ${changed === 1 ? 'word' : 'words'} changed` }
}

/** What the server's quick route says back with the job. */
export interface QuickAnswer { route: 'fast' | 'full'; reason: string }

/** The quick job's result: when the take did not fit (or needs a yes), the sentence for the full turn. */
export interface QuickFallback { text: string; note: string }
