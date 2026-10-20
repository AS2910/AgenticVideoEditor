import { useCallback, useEffect, useState } from 'react'
import type { ReviewComment } from '../types'
import { listReviewComments } from '../api'
import { clock } from '../transcript/format'
import { said } from '../pages/fmt'

const EVERY_MS = 20_000

/** C2: the video's review comments, read on open, every 20 s while the tab
 *  is visible, and after each reply or resolve. Off without the flag. */
export function useReviewComments(videoId: string | null, on: boolean) {
  const [comments, setComments] = useState<ReviewComment[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    if (!videoId || !on) return
    listReviewComments(videoId).then((r) => { setComments(r.comments ?? []); setError(null) }).catch((e) => setError(said(e, 'Could not read the comments.')))
  }, [videoId, on])
  useEffect(() => {
    setComments(null)
    load()
    if (!videoId || !on) return
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') load() }, EVERY_MS)
    return () => window.clearInterval(t)
  }, [videoId, on, load])
  const replace = (c: ReviewComment) => setComments((all) => all?.map((x) => (x.comment_id === c.comment_id ? { ...x, ...c } : x)) ?? null)
  return { comments, error, reload: load, replace }
}

/** The sentence a comment becomes when handed to Voltage. */
export const commentGoal = (c: ReviewComment) =>
  `${c.author_name} asked at ${clock(c.at_s)}${c.version != null ? ` in v${c.version}` : ''}: "${c.text}". Do what they asked.`
