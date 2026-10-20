import { describe, expect, it } from 'vitest'
import type { ActivityJob, PlanItem, TurnView } from '../types'
import { aboutEta, ago, coalesce, mergeJob, rowChip, stripState, turnSteps, turnSummary } from './model'

let n = 0
const job = (over: Partial<ActivityJob> = {}): ActivityJob => ({
  job_id: `J${++n}`, video_id: 'p1', turn_id: 't1', kind: 'voice_line', status: 'queued', step_label: 'Queued', progress: 0,
  line_ids: [], created_at: `2026-10-20T10:00:${String(n).padStart(2, '0')}Z`, started_at: null, finished_at: null, eta_s: 10,
  error_code: null, error_text: null, cost_usd: null, ...over,
})
const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 1, end: 2 }, old_text: 'old', new_text: 'new', speaker: null, mix: 'replace', delivery: null,
  reason: '', kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null, question: null, error: null,
  note: null, progress: null, ...over,
} as PlanItem)
const take = { candidate_id: 'c7' } as PlanItem['candidate']
const turn = (over: Partial<TurnView> = {}): TurnView => ({ turn_id: 't1', status: 'running', step: 'Thinking', started_at: '2026-10-20T10:00:00Z', finished_at: null, ...over })

describe('ETA', () => {
  it('is never 0 or negative, and absent when unknown', () => {
    expect(aboutEta(0)).toBeNull()
    expect(aboutEta(-3)).toBeNull()
    expect(aboutEta(null)).toBeNull()
    expect(aboutEta(0.2)).toBe('about 1 s')
    expect(aboutEta(12)).toBe('about 12 s')
    expect(aboutEta(130)).toBe('about 2 min')
  })
  it('says how long ago in words', () => {
    const now = Date.parse('2026-10-20T10:02:00Z')
    expect(ago('2026-10-20T10:00:00Z', now)).toBe('2 min ago')
    expect(ago('2026-10-20T10:01:50Z', now)).toBe('just now')
  })
})

describe('jobs merge', () => {
  it('keeps one record per id, newest first', () => {
    const a = job({ job_id: 'A', created_at: '2026-10-20T10:00:01Z' })
    const b = job({ job_id: 'B', created_at: '2026-10-20T10:00:02Z' })
    const merged = mergeJob(mergeJob(mergeJob([], a), b), { ...a, status: 'running' })
    expect(merged.map((j) => [j.job_id, j.status])).toEqual([['B', 'queued'], ['A', 'running']])
  })
})

describe('row chip: exactly one state per line', () => {
  it('goes Queued -> Voicing -> Ready to hear -> Rendering -> In the video', () => {
    const q = job({ line_ids: ['i1'] })
    expect(rowChip({ item: item(), jobs: [q] }).label).toBe('Queued')
    const r = { ...q, status: 'running' as const, progress: 0.4, step_label: 'Voicing' }
    const voicing = rowChip({ item: item({ status: 'working' }), jobs: [r] })
    expect(voicing.label).toBe('Voicing')
    expect(voicing.progress).toBe(0.4)
    const ready = item({ status: 'ready', candidate: take })
    const d = { ...q, status: 'done' as const }
    expect(rowChip({ item: ready, jobs: [d] }).label).toBe('Ready to hear')
    expect(rowChip({ item: ready, jobs: [d], rendering: { candidate_ids: ['c7'], edit_ids: [], item_ids: [] } }).label).toBe('Rendering')
    expect(rowChip({ item: ready, jobs: [d], video: { candidate_ids: [], edit_ids: [], item_ids: ['i1'] } }).label).toBe('In the video')
  })
  it('a failed job is Failed with its reason and the job to retry', () => {
    const f = job({ line_ids: ['i1'], status: 'failed', error_code: 'vendor_failed', error_text: 'The voice service did not answer.' })
    const chip = rowChip({ item: item({ status: 'failed', error: 'older words' }), jobs: [f] })
    expect(chip.label).toBe('Failed')
    expect(chip.reason).toBe('The voice service did not answer.')
    expect(chip.job?.job_id).toBe(f.job_id)
  })
  it('a kept line is In the video only when the playing render carries it', () => {
    expect(rowChip({ editId: 'e2', jobs: [], video: { candidate_ids: [], edit_ids: ['e2'], item_ids: [] } }).label).toBe('In the video')
    expect(rowChip({ editId: 'e2', jobs: [], video: { candidate_ids: [], edit_ids: [], item_ids: [] } }).label).toBe('Ready to hear')
    expect(rowChip({ editId: 'e2', jobs: [], video: null, videoUnknown: true }).label).toBe('In the video')
  })
  it('a line nobody touched is Original', () => {
    expect(rowChip({ jobs: [] }).label).toBe('Original')
  })
})

describe('the turn step list', () => {
  it('advances in place: plan, voicing k of N, fit check, render', () => {
    const t = turn()
    expect(turnSteps(t, []).map((s) => [s.label, s.state])).toEqual([['Planning', 'running']])
    const jobs = [1, 2, 3, 4, 5].map((k) => job({ line_ids: [`i${k}`] }))
    jobs[0] = { ...jobs[0], status: 'done' }
    jobs[1] = { ...jobs[1], status: 'running', step_label: 'Voicing' }
    const list = [...jobs].reverse()
    expect(turnSteps(t, list).map((s) => [s.label, s.state])).toEqual([
      ['Plan ready', 'done'], ['Voicing line 2 of 5', 'running'], ['Fit check', 'running'], ['Render preview', 'todo'],
    ])
    const done = jobs.map((j) => ({ ...j, status: 'done' as const }))
    const render = job({ kind: 'render_preview', status: 'running', detail: { version: 5 }, eta_s: 8, created_at: '2026-10-20T10:01:00Z' })
    expect(turnSteps(t, [render, ...done.reverse()]).map((s) => [s.label, s.state])).toEqual([
      ['Plan ready', 'done'], ['Voiced 5 lines', 'done'], ['Fit check', 'done'], ['Render preview v5 · about 8 s', 'running'],
    ])
  })
  it('ends with one summary', () => {
    const jobs = [1, 2, 3, 4, 5].map((k) => job({ line_ids: [`i${k}`], status: 'done' }))
    const render = job({ kind: 'render_preview', status: 'done', detail: { version: 5 } })
    const t = turn({ status: 'done', spent_usd: 0.09 })
    expect(turnSummary(t, [render, ...jobs], 5)).toBe('Done. 5 lines voiced, v5 is playing. $0.09 spent.')
    expect(turnSummary(t, [render, ...jobs], 4)).toBe('Done. 5 lines voiced, v5 is ready. $0.09 spent.')
  })
})

describe('the status strip', () => {
  it('names the line, the voice and the time left', () => {
    const jobs = [
      job({ status: 'done', line_ids: ['i1'] }),
      job({ status: 'running', line_ids: ['i2'], detail: { voice_name: 'Jeevan' }, eta_s: 12 }),
      job({ line_ids: ['i3'] }), job({ line_ids: ['i4'] }), job({ line_ids: ['i5'] }),
    ].reverse()
    expect(stripState({ jobs, turn: turn(), playing: null, stale: false }).text).toBe('Voicing line 2 of 5 · Jeevan · about 12 s')
    const checking = jobs.map((j) => (j.status === 'running' ? { ...j, step_label: 'Checking fit' } : j))
    expect(stripState({ jobs: checking, turn: turn(), playing: null, stale: false }).text).toBe('Checking fit · line 2 of 5')
  })
  it('then the render, then ready, then quiet', () => {
    const r = job({ kind: 'render_preview', status: 'running', detail: { version: 4 }, eta_s: null })
    expect(stripState({ jobs: [r], turn: null, playing: null, stale: false }).text).toBe('Rendering preview v4')
    const playing = { version: 4, created_at: '2026-10-20T10:00:00Z' }
    expect(stripState({ jobs: [], turn: null, playing, stale: false, justReady: true }).text).toBe('Ready. v4 is playing')
    expect(stripState({ jobs: [], turn: null, playing, stale: false, now: Date.parse('2026-10-20T10:02:00Z') }).text).toBe('Up to date · v4 · 2 min ago')
    expect(stripState({ jobs: [], turn: null, playing, stale: true }).text).toBe('Changes not in preview yet')
  })
})

describe('toasts', () => {
  it('coalesce into one', () => {
    const a = coalesce(null, { id: '1', text: '1 line ready', tone: 'ok' })
    expect(coalesce(coalesce(a, { id: '2', text: '1 line ready', tone: 'ok' }), { id: '3', text: '1 line ready', tone: 'ok' }).text).toBe('3 lines ready')
    const f = coalesce({ id: '4', text: 'A line failed: x', tone: 'fail' }, { id: '5', text: 'A render failed: y', tone: 'fail' })
    expect(f.text).toBe('2 jobs failed. Open Activity to retry.')
    expect(coalesce(f, { id: '6', text: '1 line ready', tone: 'ok' }).tone).toBe('fail')
    const swap = { id: '7', text: 'v5 ready. Switch now?', tone: 'ok' as const, action: { label: 'Switch now', key: 'swap' } }
    expect(coalesce(swap, { id: '8', text: 'Done. 5 lines voiced.', tone: 'ok' }).text).toBe('v5 ready. Switch now?')
  })
})

describe('A1: a bring-up-to-date job on the strip', () => {
  it('gives way to the turn it wraps, and speaks for itself when nothing else runs', () => {
    const update = job({ kind: 'brief_update', status: 'running', step_label: 'Checking what the change touches', turn_id: null, eta_s: null })
    expect(stripState({ jobs: [update], turn: turn({ step: 'Reading the lines' }), playing: null, stale: false }).text).toBe('Reading the lines')
    expect(stripState({ jobs: [update], turn: null, playing: null, stale: false }).text).toBe('Checking what the change touches')
  })
})
