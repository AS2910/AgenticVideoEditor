import { useEffect, useState } from 'react'
import type { UsageReport, UserSettings } from '../types'
import type { Me } from '../api'
import { getUsageReport, getUserSettings } from '../api'
import { hrefFor } from '../lib/route'
import { Shell, SideNav } from './Shell'
import { FillBar } from './bits'
import { usd } from './fmt'

/** Billing, said plainly: there is no billing system in this build. The ceilings are real;
 *  the plan, the card and the invoices are not, and the page says so instead of pretending. */
export function BillingPage({ me }: { me: Me | null }) {
  const [report, setReport] = useState<UsageReport | null>(null)
  const [settings, setSettings] = useState<UserSettings | null>(null)
  useEffect(() => {
    let live = true
    getUsageReport('month').then((r) => { if (live) setReport(r) }).catch(() => { /* the tiles say so */ })
    getUserSettings().then((s) => { if (live) setSettings(s) }).catch(() => { /* likewise */ })
    return () => { live = false }
  }, [])
  const share = report && report.ceiling_usd > 0 ? report.spent_usd / report.ceiling_usd : 0
  const top = report?.by_video.reduce<UsageReport['by_video'][number] | null>((a, b) => (a === null || b.spent_usd > a.spent_usd ? b : a), null) ?? null
  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
  const cell = 'flex flex-col gap-2 rounded-[10px] bg-sunk p-4'

  return (
    <Shell active="billing" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="billing" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]">
        <h1 className="disp rise m-0 mb-3 text-[56px] leading-none font-bold">Billing</h1>

        <div className="rise flex flex-wrap items-center gap-6 rounded-xl border-[1.5px] border-ink bg-ink p-[22px] text-ptext shadow-volt-lg">
          <div className="flex flex-[1_1_280px] flex-col gap-1.5">
            <span className="tag text-volt">Your plan</span>
            <span className="disp text-4xl font-bold">No plan yet</span>
            <span className="text-pmuted">Billing isn't set up in this build. Nothing is charged; spend is only counted against the ceilings below.</span>
          </div>
        </div>

        <section className={`${card} flex flex-col gap-4`} aria-labelledby="ceil-h">
          <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="ceil-h" className="disp m-0 text-[22px] font-bold">Spending ceilings</h2><span className="tag text-faint">what keeps a session from running away</span></div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3.5">
            <div className={cell}>
              <span className="tag text-faint">Monthly</span>
              <span className="disp text-[30px] font-bold">{report ? usd(report.spent_usd) : '…'} <span className="text-base text-muted-foreground">/ {report ? usd(report.ceiling_usd) : '…'}</span></span>
              <FillBar share={share} height={10} strong label="Spent against the monthly ceiling" />
            </div>
            <div className={cell}>
              <span className="tag text-faint">Per project</span>
              <span className="disp text-[30px] font-bold">{report ? usd(report.project_cap_usd) : '…'}</span>
              <span className="text-[13px] text-muted-foreground">{top ? `Highest so far: ${top.filename} at ${usd(top.spent_usd)}` : 'No project has spent anything this month.'}</span>
            </div>
            <div className={cell}>
              <span className="tag text-faint">Per turn</span>
              <span className="disp text-[30px] font-bold">{settings ? usd(settings.turn_usd) : '…'}</span>
              <a href={hrefFor({ page: 'settings' })} className="text-[13px] text-muted-foreground">Change in settings</a>
            </div>
          </div>
          <p className="m-0 text-[13px] text-muted-foreground">The monthly and project ceilings are fixed by this build; there is no way to raise them yet.</p>
        </section>

        <section className={`${card} flex flex-wrap items-center gap-[18px]`} aria-labelledby="pay-h">
          <span aria-hidden="true" className="h-9 w-[54px] rounded-md border-[1.5px] border-foreground bg-sunk" />
          <div className="flex flex-[1_1_220px] flex-col"><h2 id="pay-h" className="m-0 text-sm font-semibold">Payment method</h2><span className="text-muted-foreground">Nothing on file. This build doesn't take payments.</span></div>
        </section>

        <section className={card} aria-labelledby="inv-h">
          <h2 id="inv-h" className="disp m-0 mb-2 text-[22px] font-bold">Invoices</h2>
          <p className="m-0 text-muted-foreground">No invoices. Nothing has been charged.</p>
        </section>
      </div>
    </Shell>
  )
}
