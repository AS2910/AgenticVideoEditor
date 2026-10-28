import { useCallback, useEffect, useRef, useState } from 'react'
import { eventsUrl, getJobs, getLatestRender } from '../api'
import type { ActivityJob, QueueItem, RenderState, TurnView, VideoLock } from '../types'
import { isActive, mergeJob } from './model'
import { noteJob } from '../lib/lastJob'

export interface Activity {
  jobs: ActivityJob[]
  turn: TurnView | null
  renders: { final: RenderState | null; proposals: RenderState | null }
  /** 2026-10-25: what holds the video while it is Working (null when Ready), what is up next, and whether Up next is paused. */
  lock: VideoLock | null
  queue: QueueItem[]
  queuePaused: boolean
  /** The outcome of the last release ("done", "failed", "stopped"), with a counter so each one is heard once. */
  released: { outcome: string | null; n: number }
  /** Read everything again (after a reconnect, or when Activity opens with `all`). */
  refresh: (all?: boolean) => Promise<void>
  /** Fold a job the editor got from a request straight in, before its event arrives. */
  take: (job: ActivityJob) => void
}

/** A job's step changed or it finished: what the toasts and the tab title hear. */
export type JobListener = (job: ActivityJob, before: ActivityJob | null) => void

const POLL_MS = 1500

/** One processing model (2026-10-20): the video's jobs, its turn and where its
 *  renders stand, restored from GET /jobs?active=1 on open (a reload mid-job
 *  comes back as it was) and kept live by the events channel. Without
 *  EventSource, or while it is down, the same GET is polled while anything runs. */
export function useActivity(videoId: string | null, onJob?: JobListener, busy = false): Activity {
  const [jobs, setJobs] = useState<ActivityJob[]>([])
  const [turn, setTurn] = useState<TurnView | null>(null)
  const [renders, setRenders] = useState<Activity['renders']>({ final: null, proposals: null })
  const [lock, setLock] = useState<VideoLock | null>(null)
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [queuePaused, setQueuePaused] = useState(false)
  const [released, setReleased] = useState<Activity['released']>({ outcome: null, n: 0 })
  const known = useRef(new Map<string, ActivityJob>())
  const listener = useRef(onJob)
  listener.current = onJob
  const live = useRef(false)

  const take = useCallback((job: ActivityJob) => {
    const before = known.current.get(job.job_id) ?? null
    // A finished job never goes back (an event that arrives late is older news).
    if (before && !isActive(before) && isActive(job)) return
    known.current.set(job.job_id, job)
    noteJob(job.job_id, job.created_at ?? '')          // item 11: what "Send feedback" attaches
    setJobs((all) => mergeJob(all, job))
    if (!before || before.status !== job.status || before.step_label !== job.step_label) listener.current?.(job, before)
  }, [])

  const readRenders = useCallback(async (id: string) => {
    const [final, proposals] = await Promise.all([
      getLatestRender(id, 'final').catch(() => null),
      getLatestRender(id, 'proposals').catch(() => null),
    ])
    setRenders({ final, proposals })
  }, [])

  const refresh = useCallback(async (all = false) => {
    if (!videoId) return
    try {
      const r = await getJobs(videoId, !all)
      for (const j of [...r.jobs].reverse()) take(j)
      setTurn(r.turn)
      if (r.lock !== undefined) setLock(r.lock)
      if (r.queue !== undefined) setQueue(r.queue)
      if (r.queue_paused !== undefined) setQueuePaused(r.queue_paused)
    } catch {
      // the next event or tick reads again
    }
    await readRenders(videoId)
  }, [videoId, take, readRenders])

  // Open: restore, then listen.
  useEffect(() => {
    known.current = new Map()
    setJobs([])
    setTurn(null)
    setRenders({ final: null, proposals: null })
    setLock(null)
    setQueue([])
    setQueuePaused(false)
    if (!videoId) return
    void refresh()
    if (typeof EventSource === 'undefined') return
    const source = new EventSource(eventsUrl(videoId), { withCredentials: true })
    let dropped = false
    source.onopen = () => {
      live.current = true
      // Back after a drop: whatever happened meanwhile is read once.
      if (dropped) { dropped = false; void refresh() }
    }
    source.onerror = () => { live.current = false; dropped = true }
    source.addEventListener('job.updated', (e) => { try { take(JSON.parse((e as MessageEvent).data)) } catch { /* a bad frame is skipped */ } })
    source.addEventListener('turn.updated', (e) => { try { setTurn(JSON.parse((e as MessageEvent).data)) } catch { /* skipped */ } })
    // 2026-10-25: Ready or Working, and what is up next.
    type LockNews = VideoLock & { queue?: QueueItem[]; queue_paused?: boolean; outcome?: string | null }
    const queueNews = (d: { queue?: QueueItem[]; queue_paused?: boolean }) => {
      if (d.queue) setQueue(d.queue)
      if (d.queue_paused !== undefined) setQueuePaused(d.queue_paused)
    }
    source.addEventListener('video.locked', (e) => {
      try { const { queue: q, queue_paused: p, ...held } = JSON.parse((e as MessageEvent).data) as LockNews; setLock(held as VideoLock); queueNews({ queue: q, queue_paused: p }) } catch { /* skipped */ }
    })
    source.addEventListener('video.unlocked', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as LockNews
        setLock(null)
        queueNews(d)
        if (d.outcome) setReleased((r) => ({ outcome: d.outcome ?? null, n: r.n + 1 }))
      } catch { /* skipped */ }
    })
    source.addEventListener('queue.updated', (e) => { try { queueNews(JSON.parse((e as MessageEvent).data)) } catch { /* skipped */ } })
    source.addEventListener('render.updated', (e) => {
      try {
        const state = JSON.parse((e as MessageEvent).data) as RenderState
        setRenders((r) => ({ ...r, [state.mode]: state }))
      } catch { /* skipped */ }
    })
    return () => { live.current = false; source.close() }
  }, [videoId, refresh, take])

  // No live channel: poll while something runs (or the editor knows it just started something).
  const running = busy || !!lock || jobs.some(isActive) || turn?.status === 'running' || turn?.status === 'stopping'
    || !!renders.final?.in_progress || !!renders.proposals?.in_progress
  useEffect(() => {
    if (!videoId || !running) return
    if (!live.current) void refresh()
    const tick = window.setInterval(() => { if (!live.current) void refresh() }, POLL_MS)
    return () => window.clearInterval(tick)
  }, [videoId, running, refresh])

  // Without the live channel, a lock that went away is heard by the poll: once, as a release.
  const wasLocked = useRef(false)
  useEffect(() => {
    if (wasLocked.current && !lock && !live.current) setReleased((r) => ({ outcome: 'done', n: r.n + 1 }))
    wasLocked.current = !!lock
  }, [lock])

  return { jobs, turn, renders, refresh, take, lock, queue, queuePaused, released }
}
