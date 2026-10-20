import { useCallback, useEffect, useRef, useState } from 'react'
import { eventsUrl, getJobs, getLatestRender } from '../api'
import type { ActivityJob, RenderState, TurnView } from '../types'
import { isActive, mergeJob } from './model'

export interface Activity {
  jobs: ActivityJob[]
  turn: TurnView | null
  renders: { final: RenderState | null; proposals: RenderState | null }
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
  const known = useRef(new Map<string, ActivityJob>())
  const listener = useRef(onJob)
  listener.current = onJob
  const live = useRef(false)

  const take = useCallback((job: ActivityJob) => {
    const before = known.current.get(job.job_id) ?? null
    // A finished job never goes back (an event that arrives late is older news).
    if (before && !isActive(before) && isActive(job)) return
    known.current.set(job.job_id, job)
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
    source.addEventListener('render.updated', (e) => {
      try {
        const state = JSON.parse((e as MessageEvent).data) as RenderState
        setRenders((r) => ({ ...r, [state.mode]: state }))
      } catch { /* skipped */ }
    })
    return () => { live.current = false; source.close() }
  }, [videoId, refresh, take])

  // No live channel: poll while something runs (or the editor knows it just started something).
  const running = busy || jobs.some(isActive) || turn?.status === 'running' || turn?.status === 'stopping'
    || !!renders.final?.in_progress || !!renders.proposals?.in_progress
  useEffect(() => {
    if (!videoId || !running) return
    if (!live.current) void refresh()
    const tick = window.setInterval(() => { if (!live.current) void refresh() }, POLL_MS)
    return () => window.clearInterval(tick)
  }, [videoId, running, refresh])

  return { jobs, turn, renders, refresh, take }
}
