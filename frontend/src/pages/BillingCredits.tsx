import { useCallback, useEffect, useState } from 'react'
import type { BillingView } from '../types'
import { changePlan, getBilling, invoiceUrl, putBillingDetails, topUp, verifyRazorpay } from '../api'
import { clearCheckoutParam, returnedFromCheckout, startCheckout } from '../lib/checkout'
import { cn } from '@/lib/utils'
import { FillBar } from './bits'
import { said } from './fmt'

const COUNTRIES: [string, string][] = [['IN', 'India'], ['US', 'United States'], ['GB', 'United Kingdom'], ['AE', 'United Arab Emirates'], ['SG', 'Singapore'], ['AU', 'Australia'], ['CA', 'Canada']]
const money = (n: number, currency: 'USD' | 'INR') => (currency === 'INR' ? `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : `$${n.toFixed(2)}`)
const credits = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(2)} ${Math.abs(n) === 1 ? 'credit' : 'credits'}`

/** G3 (golive.g3): plan, credits, top-ups, billing details and invoices. Payments go through a
 *  fake provider (Stripe outside India, Razorpay in India), clearly in test mode: no card, no money;
 *  with real keys, through the provider's own checkout (lib/checkout.ts).
 *  Credits are dollars of work; "about N minutes" shows only once a cost per exported minute is measured. */
export function BillingCredits() {
  const [view, setView] = useState<BillingView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [details, setDetails] = useState({ country: '', legal_name: '', gstin: '', state_code: '' })

  const take = useCallback((v: BillingView) => {
    setView(v)
    setDetails({ country: v.account.country ?? '', legal_name: v.account.legal_name, gstin: v.account.gstin, state_code: v.account.state_code ?? '' })
  }, [])
  const load = useCallback(() => {
    setError(null)
    getBilling().then(take).catch((e) => setError(said(e, 'Billing could not be read.')))
  }, [take])
  useEffect(() => { load() }, [load])

  // Back from Stripe's page: the webhook grants the credits, usually within seconds, so read again twice.
  useEffect(() => {
    const back = returnedFromCheckout()
    if (!back) return
    clearCheckoutParam()
    if (back === 'cancelled') { setStatus('Payment cancelled. Nothing was charged.'); return }
    setStatus('Payment received. Your credits show here as soon as the payment is confirmed.')
    const timers = [3000, 10000].map((ms) => window.setTimeout(load, ms))
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [load])

  const run = async (key: string, call: () => Promise<BillingView>, done: (v: BillingView) => string) => {
    setBusy(key); setActionError(null); setStatus(null)
    try { const v = await call(); take(v); setStatus(done(v)) } catch (e) { setActionError(said(e, 'That did not go through. Try again.')) } finally { setBusy(null) }
  }

  /** A plan or a top-up. A fake provider pays at once (an invoice); a real one answers with a checkout:
   *  Stripe's page (we leave for it) or Razorpay's window (its signed payment is verified here). */
  const buy = async (key: string, call: () => Promise<BillingView>, done: (v: BillingView) => string) => {
    setBusy(key); setActionError(null); setStatus(null)
    let leaving = false
    try {
      const v = await call(); take(v)
      if (!v.checkout) { setStatus(done(v)); return }
      const out = await startCheckout(v.checkout)
      if (out.kind === 'left') { leaving = true; setStatus('Opening the payment page…'); return }
      if (out.kind === 'closed') { setStatus('Payment window closed. Nothing was charged.'); return }
      const paid = await verifyRazorpay(out.paid); take(paid)
      setStatus(`Paid. Invoice ${paid.invoice?.number ?? ''}.`.replace(' .', '.'))
    } catch (e) { setActionError(said(e, 'That did not go through. Nothing was charged. Try again.')) } finally { if (!leaving) setBusy(null) }
  }

  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
  if (error) return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
      {error}<button type="button" className="btn sm" onClick={load}>Try again</button>
    </div>
  )
  if (!view) return <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading your plan and credits…</p>
  const c = view.credits
  const india = details.country === 'IN'

  return (
    <>
      <div className="rise flex flex-wrap items-center gap-6 rounded-xl border-[1.5px] border-ink bg-ink p-[22px] text-ptext shadow-volt-lg" data-money-scope="all" data-testid="credits-card">
        <div className="flex flex-[1_1_280px] flex-col gap-1.5">
          <span className="flex flex-wrap items-center gap-2"><span className="tag text-volt">Your plan</span>{view.provider.test_mode && <span className="stamp need">Test mode</span>}</span>
          <span className="disp text-4xl font-bold">{view.plan ? view.plan.name : 'Free trial'}</span>
          <span className="text-pmuted">{view.plan ? `${credits(view.plan.credits)} a month, plus any top-ups. A month's unused plan credits lapse when the month ends.` : `${credits(view.trial_credits)} to start, free. Pick a plan or top up when you need more.`}</span>
        </div>
        <div className="flex flex-[1_1_240px] flex-col gap-2">
          <span className="tag text-pmuted">Credits left</span>
          <span className="disp text-[30px] font-bold" data-testid="credits-left">{credits(Math.max(0, c.left))}</span>
          <FillBar share={c.share ?? 0} height={10} label="Credits used" />
          <span className="text-[13px] text-pmuted">{c.minutes != null ? `About ${c.minutes} ${c.minutes === 1 ? 'minute' : 'minutes'} of finished video at what a minute has cost so far. ` : ''}{`${credits(c.used)} used of ${credits(c.granted)}${c.lapsed ? `, ${credits(c.lapsed)} lapsed` : ''}. One credit is $1 of work.`}</span>
        </div>
      </div>
      {c.left <= 0 && <p className="m-0 rounded-lg border-[1.5px] border-warn bg-card px-3 py-2 text-sm" role="status" data-testid="credits-out"><span className="stamp need mr-2">Paused</span>Your credits are used up, so paid steps are paused. Top up or pick a plan to carry on.</p>}
      {status && <p className="m-0 text-sm" role="status" data-testid="billing-status">{status}</p>}
      {actionError && <p className="m-0 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{actionError}</p>}

      <section className={`${card} flex flex-col gap-3`} aria-labelledby="plans-h" data-money-scope="all">
        <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="plans-h" className="disp m-0 text-[22px] font-bold">Plans</h2><span className="tag text-faint">billed monthly · reviewers are free</span></div>
        {view.plans.map((p) => (
          <div key={p.plan_id} className="flex flex-wrap items-center gap-3 border-t border-line pt-3" data-testid="plan-row">
            <div className="flex min-w-0 flex-[1_1_240px] flex-col"><span className="font-semibold">{p.name} <span className="tag text-faint">{credits(p.credits)} a month</span></span><span className="text-[13px] text-muted-foreground">{p.blurb}</span></div>
            <span className="tnum">{money(p.price, p.currency)} a month</span>
            {view.account.plan === p.plan_id ? <span className="stamp">Your plan</span> : (
              <button type="button" className="btn sm" disabled={busy !== null} aria-busy={busy === `plan-${p.plan_id}` || undefined}
                onClick={() => void buy(`plan-${p.plan_id}`, () => changePlan(p.plan_id), (v) => `You are on ${p.name}. ${credits(p.credits)} added for this month. Paid in test mode: no money moved. Invoice ${v.invoice?.number ?? ''}.`.replace(' .', '.'))}>
                {busy === `plan-${p.plan_id}` ? 'Paying…' : `Switch to ${p.name}`}
              </button>
            )}
          </div>
        ))}
      </section>

      <section className={`${card} flex flex-col gap-3`} aria-labelledby="topup-h" data-money-scope="all">
        <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="topup-h" className="disp m-0 text-[22px] font-bold">Top up</h2><span className="tag text-faint">credits last 12 months</span></div>
        <p className="m-0 text-[13px] text-muted-foreground">Paid through {view.provider.label}. {view.provider.test_mode ? 'Test mode: no card is asked for and no money moves.' : ''}</p>
        <div className="flex flex-wrap gap-2.5">
          {view.topups.map((t) => (
            <button key={t.credits} type="button" className="btn" disabled={busy !== null} aria-busy={busy === `top-${t.credits}` || undefined}
              onClick={() => void buy(`top-${t.credits}`, () => topUp(t.credits), () => `${credits(t.credits)} added. Paid in test mode: no money moved.`)}>
              {busy === `top-${t.credits}` ? 'Paying…' : `${credits(t.credits)} · ${money(t.price, t.currency)}`}
            </button>
          ))}
        </div>
      </section>

      <section className={`${card} flex flex-col gap-3`} aria-labelledby="details-h">
        <h2 id="details-h" className="disp m-0 text-[22px] font-bold">Billing details</h2>
        <p className="m-0 text-[13px] text-muted-foreground">Where you are billed decides the currency and the provider: India in rupees through Razorpay, elsewhere in dollars through Stripe. Indian invoices carry GST.</p>
        <form className="grid gap-3 sm:grid-cols-2" aria-label="Billing details" onSubmit={(e) => {
          e.preventDefault()
          void run('details', () => putBillingDetails({ country: details.country || null, legal_name: details.legal_name, gstin: india ? details.gstin : '', state_code: india ? details.state_code || null : null }), () => 'Billing details saved.')
        }}>
          <label className="flex flex-col gap-1 text-[13px] font-semibold">Country
            <select className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal" value={details.country} onChange={(e) => setDetails((d) => ({ ...d, country: e.target.value }))}>
              <option value="">Choose…</option>
              {COUNTRIES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-semibold">Legal name (optional)
            <input className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal" value={details.legal_name} maxLength={200} onChange={(e) => setDetails((d) => ({ ...d, legal_name: e.target.value }))} />
          </label>
          {india && (
            <>
              <label className="flex flex-col gap-1 text-[13px] font-semibold">GSTIN (optional)
                <input className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal uppercase" value={details.gstin} maxLength={15} placeholder="29ABCDE1234F1Z5" onChange={(e) => setDetails((d) => ({ ...d, gstin: e.target.value }))} />
              </label>
              <label className="flex flex-col gap-1 text-[13px] font-semibold">State
                <select className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal" value={details.state_code} disabled={!!details.gstin.trim()} onChange={(e) => setDetails((d) => ({ ...d, state_code: e.target.value }))}>
                  <option value="">Choose…</option>
                  {view.states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                </select>
              </label>
            </>
          )}
          <div className="sm:col-span-2"><button type="submit" className={cn('btn volt sm')} disabled={busy !== null}>{busy === 'details' ? 'Saving…' : 'Save details'}</button></div>
        </form>
      </section>

      <section className={card} aria-labelledby="inv-h" data-money-scope="all">
        <h2 id="inv-h" className="disp m-0 mb-2 text-[22px] font-bold">Invoices</h2>
        {view.invoices.length === 0 ? <p className="m-0 text-muted-foreground">No invoices yet. Each plan or top-up makes one.</p> : view.invoices.map((i) => (
          <div key={i.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-line py-2.5" data-testid="invoice-row">
            <span className="tnum text-[13px]">{i.number}</span>
            <span className="min-w-0 flex-1">{i.description}{i.test_mode && <span className="tag ml-2 text-faint">test mode</span>}</span>
            <span className="tnum text-[13px]">{money(i.total, i.currency)}{i.tax_kind === 'intra' ? ' incl. CGST and SGST' : i.tax_kind === 'inter' ? ' incl. IGST' : ''}</span>
            <a className="act" href={invoiceUrl(i.id)} target="_blank" rel="noreferrer">View invoice</a>
          </div>
        ))}
      </section>
    </>
  )
}
