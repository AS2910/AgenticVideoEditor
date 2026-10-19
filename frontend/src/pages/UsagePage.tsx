import { useEffect, useState } from 'react'
import type { UsageReport } from '../types'
import type { Me } from '../api'
import { getUsageReport } from '../api'
import { hrefFor } from '../lib/route'
import { Shell } from './Shell'
import { FillBar, Tile } from './bits'
import { monthLong, said, usd } from './fmt'

type Period = UsageReport['period']
const PERIODS: { key: Period; label: string }[] = [{ key: 'week', label: 'Week' }, { key: 'month', label: 'Month' }, { key: 'all', label: 'All time' }]
const periodWord = (p: Period) => (p === 'week' ? 'This week' : p === 'month' ? monthLong() : 'All time')

/** Spend for a period against the ceiling, where it went by vendor, and by project. Every
 *  number is the report's; while it loads the space is held with an ellipsis and a sentence. */
export function UsagePage({ me }: { me: Me | null }) {
  const [period, setPeriod] = useState<Period>('month')
  const [report, setReport] = useState<UsageReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setLoading(true)
    setError(null)
    getUsageReport(period)
      .then((r) => { if (live) { setReport(r); setLoading(false) } })
      .catch((e) => { if (live) { setError(said(e, 'The usage report could not be read.')); setLoading(false) } })
    return () => { live = false }
  }, [period])

  // Never one period's figures under another's label.
  const r = loading ? null : report
  const dash = '…'   // a figure still loading; never a dash (no em dashes in Voltage's copy)
  const share = r && r.ceiling_usd > 0 ? r.spent_usd / r.ceiling_usd : 0
  const topVendor = r ? Math.max(0, ...r.by_vendor.map((v) => v.usd)) : 0
  const word = periodWord(period)

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

      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}

      <div className="flex flex-wrap gap-5" aria-busy={loading || undefined}>
        <div className="rise flex flex-[2_1_420px] flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-[22px] shadow-volt-lg">
          <span className="tag text-faint">Spent · {word}</span>
          <div className="flex flex-wrap items-baseline gap-3.5">
            <span className="disp text-[clamp(56px,8vw,84px)] leading-[.9] font-bold" data-testid="spent">{r ? usd(r.spent_usd) : dash}</span>
            <span className="tnum text-base text-muted-foreground">of your {r ? usd(r.ceiling_usd) : dash} monthly ceiling</span>
          </div>
          <FillBar share={share} height={18} strong label="Spent against the monthly ceiling" />
          {loading
            ? <span className="text-[13px] text-muted-foreground" role="status">Adding up {word.toLowerCase()}…</span>
            : <span className="text-[13px] text-muted-foreground">New paid work stops at the ceiling, with the reason said.{r ? ` Each project also has its own ${usd(r.project_cap_usd)} cap.` : ''} <a href={hrefFor({ page: 'billing' })} className="text-foreground">Raise the ceiling</a></span>}
        </div>
        <div className="grid flex-[1_1_260px] grid-cols-2 gap-3">
          <Tile label="Turns" value={r ? r.turns : dash} />
          <Tile label="Takes voiced" value={r ? r.takes : dash} />
          <Tile label="Voices made" value={r ? r.voices_made : dash} />
          <Tile label="Avg turn" value={r ? usd(r.avg_turn_usd) : dash} tone="ink" />
        </div>
      </div>

      <section className="flex flex-col gap-[18px] rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="vendor-h">
        <div className="flex items-baseline gap-2.5"><h2 id="vendor-h" className="disp m-0 text-[22px] font-bold">Where it went</h2><span className="tag text-faint">by vendor</span></div>
        {!r ? <p className="m-0 min-h-[60px] text-[13px] text-muted-foreground">{loading ? 'Adding up…' : 'Nothing to show.'}</p>
          : r.by_vendor.length === 0 ? <p className="m-0 text-[13px] text-muted-foreground">Nothing spent {word.toLowerCase()}.</p> : (
          <div className="flex flex-col gap-3.5">
            {r.by_vendor.map((v) => (
              <div key={v.vendor} className="grid grid-cols-[minmax(0,1fr)_70px] items-center gap-3.5 sm:grid-cols-[150px_minmax(0,1fr)_70px]">
                <span className="font-medium">{v.label}<br /><span className="tag text-faint">{v.vendor}</span></span>
                <FillBar share={topVendor > 0 ? v.usd / topVendor : 0} height={14} className="col-span-2 sm:col-span-1" />
                <span className="tnum col-start-2 row-start-1 text-right sm:col-start-auto sm:row-start-auto">{usd(v.usd)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="project-h">
        <div className="mb-4 flex items-baseline gap-2.5"><h2 id="project-h" className="disp m-0 text-[22px] font-bold">By project</h2><span className="tag text-faint">a project's ceiling spans every video in it</span></div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="[&>th]:tag [&>th]:border-b-[1.5px] [&>th]:border-foreground [&>th]:pb-2.5 [&>th]:text-left [&>th]:font-medium [&>th]:text-faint">
                <th scope="col">Project</th><th scope="col" className="text-right!">Videos</th><th scope="col" className="text-right!">Turns</th><th scope="col" className="text-right!">Spent</th><th scope="col" className="w-40 pl-6">Of its ceiling</th>
              </tr>
            </thead>
            <tbody>
              {!r || !r.by_project || r.by_project.length === 0 ? (
                <tr><td colSpan={5} className="py-3.5 text-[13px] text-muted-foreground">{loading ? 'Adding up…' : 'No project spent anything, or every video is standalone.'}</td></tr>
              ) : r.by_project.map((p) => (
                <tr key={p.project_id} className="rise transition-colors hover:bg-sunk [&>td]:border-b [&>td]:border-line [&>td]:py-3.5">
                  <td><a href={hrefFor({ page: 'folder', projectId: p.project_id })} className="font-semibold no-underline">{p.name}</a></td>
                  <td className="tnum text-right">{p.videos}</td>
                  <td className="tnum text-right">{p.turns}</td>
                  <td className="tnum text-right">{usd(p.spent_usd)}</td>
                  <td className="pl-6">{p.ceiling_usd ? <FillBar share={p.ceiling_usd > 0 ? p.spent_usd / p.ceiling_usd : 0} height={10} label={`${p.name}: ${usd(p.spent_usd)} of its ${usd(p.ceiling_usd)} ceiling`} /> : <span className="tag text-faint">no ceiling</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="video-h">
        <div className="mb-4 flex items-baseline gap-2.5"><h2 id="video-h" className="disp m-0 text-[22px] font-bold">By video</h2>{r && <span className="tag text-faint">each capped at {usd(r.project_cap_usd)}</span>}</div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="[&>th]:tag [&>th]:border-b-[1.5px] [&>th]:border-foreground [&>th]:pb-2.5 [&>th]:text-left [&>th]:font-medium [&>th]:text-faint">
                <th scope="col">Video</th><th scope="col" className="text-right!">Turns</th><th scope="col" className="text-right!">Voice chars</th><th scope="col" className="text-right!">Spent</th><th scope="col" className="w-40 pl-6">Of its cap</th>
              </tr>
            </thead>
            <tbody>
              {!r || r.by_video.length === 0 ? (
                <tr><td colSpan={5} className="py-3.5 text-[13px] text-muted-foreground">{loading ? 'Adding up…' : `No video spent anything ${word.toLowerCase()}.`}</td></tr>
              ) : r.by_video.map((p) => (
                <tr key={p.video_id} className="rise transition-colors hover:bg-sunk [&>td]:border-b [&>td]:border-line [&>td]:py-3.5">
                  <td><a href={hrefFor({ page: 'editor', projectId: p.video_id })} className="font-semibold no-underline">{p.filename}</a></td>
                  <td className="tnum text-right">{p.turns}</td>
                  <td className="tnum text-right">{p.voice_characters.toLocaleString()}</td>
                  <td className="tnum text-right">{usd(p.spent_usd)}</td>
                  <td className="pl-6"><FillBar share={p.cap_usd > 0 ? p.spent_usd / p.cap_usd : 0} height={10} label={`${p.filename}: ${usd(p.spent_usd)} of its ${usd(p.cap_usd)} cap`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  )
}
