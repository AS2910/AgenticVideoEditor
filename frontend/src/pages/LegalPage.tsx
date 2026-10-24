import { Wordmark } from '../components/Wordmark'
import { hrefFor } from '../lib/route'
import { useEffect } from 'react'
import { AbuseReport } from '../components/AbuseReport'
import { track } from '../lib/analytics'
import type { Block, LegalText, Vendor } from './legal/types'
import { TERMS } from './legal/terms'
import { PRIVACY } from './legal/privacy'
import { ACCEPTABLE_USE } from './legal/acceptableUse'

/** G6: Terms, Privacy and Acceptable Use. Drafts for a lawyer to review (SETUP_NEEDED.md), clearly
 *  marked as such; the text lives in `legal/`. Public: no account needed to read them. */
export type LegalDoc = 'terms' | 'privacy' | 'acceptable-use'

const DOCS: Record<LegalDoc, LegalText> = { terms: TERMS, privacy: PRIVACY, 'acceptable-use': ACCEPTABLE_USE }

function Blocks({ blocks }: { blocks: Block[] }) {
  return blocks.map((b, i) => {
    if (typeof b === 'string') return <p key={i} className="m-0">{b}</p>
    if (Array.isArray(b)) return <ul key={i} className="m-0 flex list-disc flex-col gap-1 pl-5">{b.map((t) => <li key={t}>{t}</li>)}</ul>
    if ('counsel' in b) {
      return (
        <aside key={i} aria-label="Note for counsel" data-testid="legal-counsel"
          className="rounded-md border-[1.5px] border-dashed border-warn bg-sunk px-3 py-2 text-sm">
          <strong>For counsel:</strong> {b.counsel}
        </aside>
      )
    }
    if ('link' in b) return <p key={i} className="m-0">{b.before} <a href={b.href}>{b.link}</a>.</p>
    return <VendorList key={i} vendors={b.vendors} />
  })
}

/** One card per service, not a table: the page stays readable at phone width. */
function VendorList({ vendors }: { vendors: Vendor[] }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0" data-testid="vendor-list">
      {vendors.map((v) => (
        <li key={v.name} className="flex flex-col gap-2 rounded-lg border border-line2 bg-card px-4 py-3">
          <h3 className="disp m-0 text-[17px] font-bold">{v.name}</h3>
          <dl className="m-0 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">What it does</dt><dd className="m-0">{v.does}</dd>
            <dt className="text-muted-foreground">What it receives</dt><dd className="m-0">{v.gets}</dd>
            <dt className="text-muted-foreground">Why</dt><dd className="m-0">{v.why}</dd>
            <dt className="text-muted-foreground">When</dt><dd className="m-0">{v.when}</dd>
            <dt className="text-muted-foreground">Where</dt><dd className="m-0">{v.where}</dd>
          </dl>
        </li>
      ))}
    </ul>
  )
}

export function LegalPage({ doc }: { doc: LegalDoc }) {
  const d = DOCS[doc]
  const jump = (id: string) => {
    const el = document.getElementById(id)
    el?.scrollIntoView({ block: 'start' })
    el?.focus({ preventScroll: true })
  }
  useEffect(() => { track('legal.opened', { doc }) }, [doc])
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="flex h-[62px] items-center gap-4 border-b-[1.5px] border-foreground bg-card px-4 sm:px-6"><Wordmark href={hrefFor({ page: 'projects' })} label="Voltage, home" /></header>
      <main className="mx-auto flex w-full max-w-[760px] flex-col gap-6 px-4 pt-10 pb-20 sm:px-6" data-testid="legal-page">
        <div className="flex flex-col gap-3">
          <span className="stamp need self-start" data-testid="legal-draft">Draft, needs legal review</span>
          <h1 className="disp m-0 text-[40px] leading-tight font-bold">{d.title}</h1>
          <p className="m-0 text-lg">{d.summary}</p>
          <p className="m-0 text-muted-foreground">This is a draft written to describe how Voltage works, for a lawyer to review. It is not legal advice and is not in force yet. Points marked "For counsel" are open questions for that review. Drafted 24 October 2026.</p>
        </div>
        <nav aria-label="On this page" className="flex flex-col gap-2 rounded-lg border border-line2 bg-card px-4 py-3">
          <h2 className="tag m-0">On this page</h2>
          <ol className="m-0 flex flex-col gap-1 pl-5 text-sm">
            {d.sections.map((s, i) => (
              <li key={s.h}><button type="button" className="text-left underline underline-offset-2" onClick={() => jump(`${doc}-${i}`)}>{s.h}</button></li>
            ))}
          </ol>
        </nav>
        {d.sections.map((s, i) => (
          <section key={s.h} className="flex flex-col gap-2" aria-labelledby={`${doc}-${i}`}>
            <h2 id={`${doc}-${i}`} tabIndex={-1} className="disp m-0 text-[22px] font-bold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">{s.h}</h2>
            <Blocks blocks={s.blocks} />
          </section>
        ))}
        <nav aria-label="Policies" className="flex flex-wrap gap-4 border-t border-line pt-4 text-sm">
          <a href="#terms">Terms of service</a><a href="#privacy">Privacy policy</a><a href="#acceptable-use">Acceptable use policy</a>
        </nav>
        {doc === 'acceptable-use' && <AbuseReport />}
      </main>
    </div>
  )
}

/** The three policy links, for footers. */
export function LegalLinks({ className = '' }: { className?: string }) {
  return (
    <nav aria-label="Policies" className={`flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground ${className}`}>
      <a className="text-muted-foreground" href="#terms">Terms</a><a className="text-muted-foreground" href="#privacy">Privacy</a><a className="text-muted-foreground" href="#acceptable-use">Acceptable use</a>
    </nav>
  )
}
