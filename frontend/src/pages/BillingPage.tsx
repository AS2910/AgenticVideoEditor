import { useEffect, useState } from 'react'
import type { SpendSummary } from '../types'
import type { Me } from '../api'
import { getSpend } from '../api'
import { hrefFor } from '../lib/route'
import { ceilingWord, usd } from '../lib/money'
import { Shell, SideNav } from './Shell'
import { useWorkspaceRole } from '../lib/useWorkspaceRole'
import { FillBar } from './bits'
import { BillingCredits } from './BillingCredits'
import { useFlags } from '../flags/useFlags'
import { track } from '../lib/analytics'

/** Billing, said plainly: there is no billing system in this build. The page holds the plan,
 *  the monthly ceiling, payment and invoices, nothing per project or per video: where the money
 *  went is the Usage page's. The monthly ceiling is real; the plan, the card and the invoices
 *  are not, and the page says so instead of pretending. */
export function BillingPage({ me }: { me: Me | null }) {
  // G3 (golive.g3): plan, credits, top-ups and invoices through fake providers, in test mode.
  const flagged = useFlags()
  const billingOn = flagged.enabled('golive.g3')
  // Rehearsal 2026-10-23: an Editor or a Reviewer is told plainly whose page this is,
  // instead of an error and a Try again that can never work.
  const role = useWorkspaceRole(flagged.enabled('golive.g2'))
  const member = role === 'editor' || role === 'reviewer'
  useEffect(() => { if (billingOn) track('billing.opened') }, [billingOn])
  const [spend, setSpend] = useState<SpendSummary | null>(null)
  useEffect(() => {
    if (member) return
    let live = true
    getSpend().then((s) => { if (live) setSpend(s) }).catch(() => { /* the tile says so */ })
    return () => { live = false }
  }, [member])
  const month = spend?.month ?? null
  const share = month?.ceiling_usd ? month.spent_usd / month.ceiling_usd : 0
  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'

  return (
    <Shell active="billing" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="billing" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]">
        <h1 className="disp rise m-0 mb-3 text-[56px] leading-none font-bold">Billing</h1>

        {member ? (
          <p className="m-0 max-w-[640px] rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" role="status" data-testid="billing-not-owner">
            <span className="stamp in mr-2">{role === 'editor' ? 'Editor' : 'Reviewer'}</span>
            Billing belongs to the workspace owner. Ask them to top up or change the plan.
          </p>
        ) : (
        <>
        {billingOn ? <BillingCredits /> : (
        <div className="rise flex flex-wrap items-center gap-6 rounded-xl border-[1.5px] border-ink bg-ink p-[22px] text-ptext shadow-volt-lg">
          <div className="flex flex-[1_1_280px] flex-col gap-1.5">
            <span className="tag text-volt">Your plan</span>
            <span className="disp text-4xl font-bold">No plan yet</span>
            <span className="text-pmuted">Billing isn't open yet. Nothing is charged; spend is only counted against the monthly ceiling below.</span>
          </div>
        </div>
        )}

        <section className={`${card} flex flex-col gap-4`} aria-labelledby="ceil-h" data-money-scope="month" data-testid="monthly-ceiling">
          <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="ceil-h" className="disp m-0 text-[22px] font-bold">Monthly ceiling</h2><span className="tag text-faint">across every project and video</span></div>
          <span className="disp text-[30px] font-bold">{month ? `${month.label}: ${usd(month.spent_usd)}` : '…'} <span className="text-base text-muted-foreground">of {month?.ceiling_usd != null ? ceilingWord(month.ceiling_usd) : '…'}</span></span>
          <FillBar share={share} height={10} strong label="Spent against the monthly ceiling" />
          <p className="m-0 text-[13px] text-muted-foreground">New paid work stops when the month reaches it; it resets on the first of the month. To change it, write to us with Send feedback in Help.</p>
          <a className="act self-start" href={hrefFor({ page: 'usage' })}>See where it went in Usage →</a>
        </section>

        {!billingOn && (
          <>
        <section className={`${card} flex flex-wrap items-center gap-[18px]`} aria-labelledby="pay-h">
          <span aria-hidden="true" className="h-9 w-[54px] rounded-md border-[1.5px] border-foreground bg-sunk" />
          <div className="flex flex-[1_1_220px] flex-col"><h2 id="pay-h" className="m-0 text-sm font-semibold">Payment method</h2><span className="text-muted-foreground">Nothing on file. No payments are taken yet.</span></div>
        </section>

        <section className={card} aria-labelledby="inv-h">
          <h2 id="inv-h" className="disp m-0 mb-2 text-[22px] font-bold">Invoices</h2>
          <p className="m-0 text-muted-foreground">No invoices. Nothing has been charged.</p>
        </section>
          </>
        )}
        </>
        )}
      </div>
    </Shell>
  )
}
