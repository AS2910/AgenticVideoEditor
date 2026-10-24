import { useEffect, useState } from 'react'
import type { KnownIssues, Me } from '../api'
import { getKnownIssues } from '../api'
import { hrefFor } from '../lib/route'
import { formatDate } from '../lib/dates'
import { Markdown } from '../components/Markdown'
import { openFeedback } from '../components/FeedbackDialog'
import { useOnboarding } from '../guides/onboarding'
import { Shell } from './Shell'
import { said } from './fmt'

/** Beta kit: the gaps we know about, read from help/known-issues.md (GET /help/known-issues).
 *  The Beta badge in the header links here. */
export function KnownIssuesPage({ me }: { me: Me | null }) {
  const [page, setPage] = useState<KnownIssues | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { markChecklist } = useOnboarding()
  useEffect(() => {
    let live = true
    getKnownIssues().then((p) => { if (live) setPage(p) }).catch((e) => { if (live) setError(said(e, 'The known issues could not be read.')) })
    return () => { live = false }
  }, [])
  // The beta's welcome checklist: read once the page is there.
  useEffect(() => { if (page) markChecklist('known-issues') }, [page, markChecklist])

  return (
    <Shell active="help" me={me} mainClassName="mx-auto flex w-full max-w-[760px] flex-col gap-7 px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="disp rise m-0 text-[44px] leading-none font-bold sm:text-[56px]">{page?.title ?? 'Known issues'}</h1>
          <span className="stamp inkd">Beta</span>
        </div>
        {page?.updated && <span className="tag text-faint">Updated {formatDate(page.updated)}</span>}
        {page?.summary && <p className="m-0 max-w-[620px] text-[17px] leading-relaxed">{page.summary}</p>}
      </div>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {!page && !error && <p className="m-0 text-muted-foreground" role="status">Loading the known issues…</p>}
      {page && page.sections.length === 0 && <p className="m-0 text-muted-foreground">Nothing known right now.</p>}
      {page?.sections.map((s, i) => (
        <section key={s.heading} className="vcard flex flex-col gap-2.5 p-[22px]" aria-labelledby={`ki-${i}`} data-testid="known-issue-section">
          <h2 id={`ki-${i}`} className="disp m-0 text-[22px] font-bold">{s.heading}</h2>
          <Markdown text={s.body} className="text-[15px] leading-relaxed" />
        </section>
      ))}
      <section className="pane flex flex-wrap items-center gap-5 rounded-[14px] px-7 py-6">
        <span className="pm flex-[1_1_320px]">Hit something that is not on this list? Tell us, with a screenshot if you can.</span>
        <a href={hrefFor({ page: 'help' })} className="btn ghost">Help</a>
        <button type="button" className="btn volt" onClick={openFeedback}>Send feedback</button>
      </section>
    </Shell>
  )
}
