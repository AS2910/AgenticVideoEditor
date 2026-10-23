import { Fragment, useEffect, useState } from 'react'
import type { UsageGroup, UsageReport } from '../types'
import type { Me } from '../api'
import { getUsageReport } from '../api'
import type { UsageScope } from '../lib/route'
import { hrefFor } from '../lib/route'
import { ceilingWord } from '../lib/money'
import { Shell } from './Shell'
import { FillBar, Tile } from './bits'
import { monthLong, said, usd } from './fmt'

type Period = UsageReport['period']
const PERIODS: { key: Period; label: string }[] = [{ key: 'week', label: 'Week' }, { key: 'month', label: 'Month' }, { key: 'all', label: 'All time' }]
const periodWord = (p: Period) => (p === 'week' ? 'This week' : p === 'month' ? monthLong() : 'All time')

/** The API's name for a scope: all, none, f3, v:p2. */
const scopeParam = (s: UsageScope | null) => (!s ? 'all' : s.kind === 'none' ? 'none' : s.kind === 'project' ? s.id : `v:${s.id}`)
/** What the totals card's figure measures, for `data-money-scope`. */
const scopeKey = (s: UsageScope | null, period: Period) => (!s ? (period === 'month' ? 'month' : 'all') : s.kind === 'none' ? 'none' : s.kind)

/** The table's groups for the chosen scope: one project, the standalone videos, or the groups that hold one video. */
function groupsFor(groups: UsageGroup[], scope: UsageScope | null): UsageGroup[] {
  if (!scope) return groups
  if (scope.kind === 'none') return groups.filter((g) => g.project_id === null)
  if (scope.kind === 'project') return groups.filter((g) => g.project_id === scope.id)
  return groups
    .map((g) => ({ ...g, project_level_usd: null, videos: g.videos.filter((v) => v.video_id === scope.id) }))
    .filter((g) => g.videos.length > 0)
}

/** Spend for a period, for a scope (everything, one project, the standalone videos, one video):
 *  the scope's totals on top (spent, ceiling, by vendor), then projects as rows with their videos
 *  nested, each video's spend while it was in that project, a Project-level row for costs that
 *  belong to no single video, and the standalone videos under "No project". Every figure names
 *  its scope; while the report loads the space is held with an ellipsis and a sentence. */
export function UsagePage({ me, scope: routed = null }: { me: Me | null; scope?: UsageScope | null }) {
  const [period, setPeriod] = useState<Period>('month')
  const [scope, setScope] = useState<UsageScope | null>(routed)
  const [report, setReport] = useState<UsageReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const param = scopeParam(scope)

  useEffect(() => { setScope(routed) }, [routed])
  useEffect(() => {
    let live = true
    setLoading(true)
    setError(null)
    getUsageReport(period, param)
      .then((r) => { if (live) { setReport(r); setLoading(false) } })
      .catch((e) => { if (live) { setError(said(e, 'The usage report could not be read.')); setLoading(false) } })
    return () => { live = false }
  }, [period, param])

  const choose = (next: UsageScope | null) => {
    setScope(next)
    window.location.hash = hrefFor({ page: 'usage', scope: next })
  }

  // Never one period's or scope's figures under another's label.
  const r = loading ? null : report
  const t = r?.totals ?? null
  const dash = '…'   // a figure still loading; never a dash (no em dashes in Voltage's copy)
  const share = t && t.ceiling_usd ? t.spent_usd / t.ceiling_usd : 0
  const vendors = t?.by_vendor ?? r?.by_vendor ?? []
  const topVendor = Math.max(0, ...vendors.map((v) => v.usd))
  const word = periodWord(period)
  const label = t?.label ?? (scope ? '' : word)
  const groups = r?.groups ? groupsFor(r.groups, scope) : []
  const projects = (report?.groups ?? []).filter((g) => g.project_id !== null)
  // A filtered table opens its groups; "All" starts folded.
  const isOpen = (key: string) => scope !== null || open.has(key)
  const toggle = (key: string) => setOpen((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n })
  const videoName = scope?.kind === 'video' ? groups.flatMap((g) => g.videos).find((v) => v.video_id === scope.id)?.filename ?? t?.label : null

  return (
    <Shell active="usage" me={me} mainClassName="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-4 pt-10 pb-20 sm:px-6 sm:pt-12">
      <div className="flex flex-wrap items-end gap-4">
        <h1 className="disp rise m-0 flex-[1_1_300px] text-[56px] leading-none font-bold">Usage</h1>
        <div role="group" aria-label="Period" className="segs">
          {PERIODS.map((p) => (
            <button key={p.key} type="button" className="seg" aria-pressed={period === p.key} onClick={() => setPeriod(p.key)}>{p.label}</button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Scope" data-testid="scope-switch">
        <div className="segs">
          <button type="button" className="seg" aria-pressed={scope === null} onClick={() => choose(null)}>All</button>
          <button type="button" className="seg" aria-pressed={scope?.kind === 'none'} onClick={() => choose({ kind: 'none' })}>Standalone videos</button>
        </div>
        <select
          className="h-[38px] min-w-[200px] rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-sm text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
          aria-label="Project"
          value={scope?.kind === 'project' ? scope.id : ''}
          onChange={(e) => choose(e.target.value ? { kind: 'project', id: e.target.value } : null)}
        >
          <option value="">{projects.length ? 'A project…' : 'No projects yet'}</option>
          {projects.map((g) => <option key={g.project_id} value={g.project_id ?? ''}>{g.name}</option>)}
        </select>
        {scope?.kind === 'video' && (
          <span className="tag inline-flex items-center gap-2 rounded-full border-[1.5px] border-foreground px-2.5 py-1">
            Video · {videoName ?? scope.id}
            <button type="button" className="act min-h-0 p-0 pointer-coarse:min-h-11 pointer-coarse:min-w-11" onClick={() => choose(null)} aria-label="Show all usage">×</button>
          </span>
        )}
      </div>

      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}

      <div className="flex flex-wrap gap-5" aria-busy={loading || undefined}>
        <div className="rise flex flex-[2_1_420px] flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-[22px] shadow-volt-lg" data-money-scope={scopeKey(scope, period)} data-testid="totals">
          <span className="tag text-faint">Spent · {label || dash}{scope && t ? ` · ${word}` : ''}</span>
          <div className="flex flex-wrap items-baseline gap-3.5">
            <span className="disp text-[clamp(56px,8vw,84px)] leading-[.9] font-bold" data-testid="spent">{t ? usd(t.spent_usd) : r ? usd(r.spent_usd) : dash}</span>
            {t?.ceiling_usd != null && <span className="tnum text-base text-muted-foreground">of {scope ? 'its' : 'your'} {ceilingWord(t.ceiling_usd)} {scope?.kind === 'project' ? 'project ceiling' : scope?.kind === 'video' ? 'video ceiling' : 'monthly ceiling'}</span>}
            {t && t.ceiling_usd == null && <span className="tnum text-base text-muted-foreground">{scope ? 'no ceiling of its own' : 'no ceiling for the period'}</span>}
            {!t && loading && <span className="tnum text-base text-muted-foreground">of {dash}</span>}
          </div>
          {t?.ceiling_usd != null && <FillBar share={share} height={18} strong label={`${t.label}: spent against its ceiling`} />}
          {loading
            ? <span className="text-[13px] text-muted-foreground" role="status">Adding up {word.toLowerCase()}…</span>
            : <span className="text-[13px] text-muted-foreground">New paid work stops at the first ceiling it meets, and the refusal names it. <a href={hrefFor({ page: 'billing' })} className="text-foreground underline underline-offset-2">Your plan and monthly ceiling</a></span>}
        </div>
        <div className="grid flex-[1_1_260px] grid-cols-2 gap-3">
          <Tile label="Turns" value={r ? r.turns : dash} />
          <Tile label="Takes voiced" value={r ? r.takes : dash} />
          <Tile label="Voices made" value={r ? r.voices_made : dash} />
          <div className="contents" data-money-scope="turn"><Tile label="Avg turn" value={r ? usd(r.avg_turn_usd) : dash} tone="ink" /></div>
        </div>
      </div>

      <section className="flex flex-col gap-[18px] rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="vendor-h">
        <div className="flex items-baseline gap-2.5"><h2 id="vendor-h" className="disp m-0 text-[22px] font-bold">Where it went</h2><span className="tag text-faint">{label ? `${label} · by vendor` : 'by vendor'}</span></div>
        {!r ? <p className="m-0 min-h-[60px] text-[13px] text-muted-foreground">{loading ? 'Adding up…' : 'Nothing to show.'}</p>
          : vendors.length === 0 ? <p className="m-0 text-[13px] text-muted-foreground">Nothing spent {word.toLowerCase()}.</p> : (
          <div className="flex flex-col gap-3.5">
            {vendors.map((v) => (
              <div key={v.vendor} className="grid grid-cols-[minmax(0,1fr)_70px] items-center gap-3.5 sm:grid-cols-[150px_minmax(0,1fr)_70px]" data-money-scope={scopeKey(scope, period)}>
                <span className="font-medium">{v.label}<br /><span className="tag text-faint">{v.vendor}</span></span>
                <FillBar share={topVendor > 0 ? v.usd / topVendor : 0} height={14} className="col-span-2 sm:col-span-1" />
                <span className="tnum col-start-2 row-start-1 text-right sm:col-start-auto sm:row-start-auto">{usd(v.usd)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="table-h">
        <div className="mb-4 flex flex-wrap items-baseline gap-2.5"><h2 id="table-h" className="disp m-0 text-[22px] font-bold">By project and video</h2><span className="tag text-faint">a video's spend is counted where it was when it spent</span></div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse" data-testid="usage-table">
            <thead>
              <tr className="[&>th]:tag [&>th]:border-b-[1.5px] [&>th]:border-foreground [&>th]:pb-2.5 [&>th]:text-left [&>th]:font-medium [&>th]:text-faint">
                <th scope="col">Project / video</th><th scope="col" className="text-right!">Spent</th><th scope="col" className="w-44 pl-6">Of its ceiling</th>
              </tr>
            </thead>
            <tbody>
              {!r || groups.length === 0 ? (
                <tr><td colSpan={3} className="py-3.5 text-[13px] text-muted-foreground">{loading ? 'Adding up…' : 'Nothing here yet.'}</td></tr>
              ) : groups.map((g) => {
                const key = g.project_id ?? 'none'
                const expanded = isOpen(key)
                const rows = g.videos.length + (g.project_level_usd !== null ? 1 : 0)
                return (
                  <Fragment key={key}>
                    <tr className="rise transition-colors hover:bg-sunk [&>td]:border-b [&>td]:border-line [&>td]:py-3" data-money-scope={g.project_id ? 'project' : 'none'} data-testid={`group-${key}`}>
                      <td>
                        <span className="flex items-center gap-2">
                          <button type="button" className="act min-h-8 w-8 justify-center p-0 pointer-coarse:min-h-11 pointer-coarse:w-11" aria-expanded={expanded} aria-label={`${expanded ? 'Fold' : 'Open'} ${g.name}`} onClick={() => toggle(key)} disabled={scope !== null || rows === 0}>
                            <span aria-hidden="true">{expanded ? '▾' : '▸'}</span>
                          </button>
                          {g.project_id
                            ? <a href={hrefFor({ page: 'folder', projectId: g.project_id })} className="font-semibold no-underline">{g.name}</a>
                            : <a href={hrefFor({ page: 'usage', scope: { kind: 'none' } })} className="font-semibold text-muted-foreground no-underline">{g.name}</a>}
                          <span className="tag text-faint">{g.videos.length} {g.videos.length === 1 ? 'video' : 'videos'}</span>
                        </span>
                      </td>
                      <td className="tnum text-right font-semibold">{usd(g.spent_usd)}</td>
                      <td className="pl-6">{g.ceiling_usd ? <FillBar share={g.spent_usd / g.ceiling_usd} height={10} label={`${g.name}: ${usd(g.spent_usd)} of its ${ceilingWord(g.ceiling_usd)} project ceiling`} /> : <span className="tag text-faint">no project ceiling</span>}</td>
                    </tr>
                    {expanded && g.videos.map((v) => (
                      <tr key={`${key}-${v.video_id}`} className="transition-colors hover:bg-sunk [&>td]:border-b [&>td]:border-line [&>td]:py-2.5" data-money-scope="video" data-testid={`row-${key}-${v.video_id}`}>
                        <td className="pl-10">
                          <a href={hrefFor({ page: 'editor', projectId: v.video_id })} className="no-underline">{v.filename}</a>
                          {!v.here && <span className="tag ml-2 text-faint">moved out · spent while here</span>}
                        </td>
                        <td className="tnum text-right">{usd(v.spent_usd)}</td>
                        <td className="pl-6"><a className="tag text-faint" href={hrefFor({ page: 'usage', scope: { kind: 'video', id: v.video_id } })}>this video only</a></td>
                      </tr>
                    ))}
                    {expanded && g.project_level_usd !== null && g.project_id && (
                      <tr className="[&>td]:border-b [&>td]:border-line [&>td]:py-2.5" data-money-scope="project" data-testid={`project-level-${key}`}>
                        <td className="pl-10"><a href={hrefFor({ page: 'folder', projectId: g.project_id })} className="no-underline">Project-level</a> <span className="tag ml-2 text-faint">project voices, reference files</span></td>
                        <td className="tnum text-right">{usd(g.project_level_usd)}</td>
                        <td />
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  )
}
