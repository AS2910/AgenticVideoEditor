import { useCallback, useEffect, useRef, useState } from 'react'
import { track } from '../lib/analytics'
import type { ProjectEvent } from '../types'
import { getProjectEvents } from '../api'
import { agoLabel } from '../lib/dates'
import { cn } from '@/lib/utils'
import { feedItems } from './feedWords'

/** C1 (projects.review): the project page's Activity panel, read from the
 *  activity log (F7, GET /projects/{id}/events), newest first, a page at a
 *  time ("Show older"). The first page is read again every few seconds while
 *  the page is open (jobs, batches and reviewers add to it), and at once
 *  when `tick` changes (a move on the board). */

const PAGE = 30
export const FEED_POLL_MS = 4000

export function ProjectFeed({ projectId, nameOf, tick = 0, pollMs = FEED_POLL_MS }: {
  projectId: string
  /** A video's file name, or null when it is no longer in the project. */
  nameOf: (videoId: string | null) => string | null
  tick?: number
  pollMs?: number
}) {
  const [events, setEvents] = useState<ProjectEvent[] | null>(null)
  const [next, setNext] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [older, setOlder] = useState(false)
  const nextRef = useRef<number | null>(null)
  const loadedOlder = useRef(false)

  /** The newest page, merged over what is shown (older pages already read stay). */
  const readNewest = useCallback(async () => {
    try {
      const page = await getProjectEvents(projectId, null, PAGE)
      setError(null)
      if (!loadedOlder.current) {
        nextRef.current = page.next
        setNext(page.next)
        setEvents(page.events)
        return
      }
      // Older pages were read: the new page goes on top, what is under it stays.
      const oldest = page.events[page.events.length - 1]?.id ?? Infinity
      setEvents((have) => [...page.events, ...(have ?? []).filter((e) => e.id < oldest)])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read the activity.')
    }
  }, [projectId])

  useEffect(() => {
    loadedOlder.current = false
    setEvents(null)
    void readNewest()
  }, [projectId, readNewest])
  useEffect(() => { if (tick > 0) void readNewest() }, [tick, readNewest])
  useEffect(() => {
    const t = setInterval(() => { if (typeof document === 'undefined' || document.visibilityState !== 'hidden') void readNewest() }, pollMs)
    return () => clearInterval(t)
  }, [readNewest, pollMs])

  const showOlder = async () => {
    if (!nextRef.current) return
    setOlder(true)
    try {
      const page = await getProjectEvents(projectId, nextRef.current, PAGE)
      loadedOlder.current = true
      track('feed.older_loaded')
      nextRef.current = page.next
      setNext(page.next)
      setEvents((have) => [...(have ?? []), ...page.events.filter((e) => !(have ?? []).some((h) => h.id === e.id))])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read older activity.')
    } finally { setOlder(false) }
  }

  const items = events ? feedItems(events, nameOf) : []
  return (
    <div className="rise flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="feed" data-tour="project-feed">
      <div className="flex items-center gap-2"><span className="disp text-xl font-bold">Activity</span><span className="flex-1" /><span className="tag text-faint">Newest first</span></div>
      {events === null && !error && <span className="text-[13px] text-muted-foreground" role="status">Reading the activity…</span>}
      {error && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border-[1.5px] border-warn px-3 py-2 text-sm" role="alert">
          <span className="flex-1">{error}</span>
          <button type="button" className="btn sm" onClick={() => void readNewest()}>Try again</button>
        </div>
      )}
      {events !== null && items.length === 0 && <span className="text-[13px] text-muted-foreground">Nothing has happened here yet. Edits, stage moves and reviews show up here as they happen.</span>}
      {items.length > 0 && (
        <ol className="m-0 flex max-h-[440px] list-none flex-col overflow-y-auto p-0 pr-1" aria-label="What happened in this project" tabIndex={0}>
          {items.map((item) => (
            <li key={item.key} className="flex items-start gap-2.5 border-t border-line py-2 first:border-t-0" data-testid="feed-item">
              <span aria-hidden="true" className={cn('mt-1.5 size-2 flex-none rounded-full border border-ink', item.actor === 'voltage' ? 'bg-volt' : item.actor === 'reviewer' ? 'bg-warn' : 'bg-card')} />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm [overflow-wrap:anywhere]">{item.text}</span>
                <span className="tag text-faint" title={item.at}>{agoLabel(item.at)}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
      {next !== null && events !== null && (
        <button type="button" className="act self-start" onClick={() => void showOlder()} disabled={older}>{older ? 'Reading…' : 'Show older'}</button>
      )}
    </div>
  )
}
