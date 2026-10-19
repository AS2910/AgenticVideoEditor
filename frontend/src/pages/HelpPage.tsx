import { useEffect, useMemo, useRef, useState } from 'react'
import type { Me } from '../api'
import { listHelp } from '../api'
import type { HelpArticle } from '../types'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { KeyboardSheet } from '../components/KeyboardSheet'
import { Markdown } from '../components/Markdown'
import { Bolt, Shell } from './Shell'
import { said } from './fmt'

export interface HelpPageProps {
  me: Me | null
  /** The articles, when the host already has them; otherwise `listHelp()` is asked. */
  articles?: HelpArticle[]
  /** `#help/<slug>`: the article to open in the reader. */
  initialSlug?: string | null
  onReplay: () => void
  onAsk: () => void
  onShowMe: (tour: string) => void
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** The sections in the order the articles name them. */
function group(articles: HelpArticle[]): { name: string; articles: HelpArticle[] }[] {
  const out: { name: string; articles: HelpArticle[] }[] = []
  for (const a of articles) {
    let s = out.find((x) => x.name === a.section)
    if (!s) { s = { name: a.section, articles: [] }; out.push(s) }
    s.articles.push(a)
  }
  for (const s of out) s.articles.sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  return out
}

/** Help: search, the tutorial, Ask Voltage, the ten sections, and an article reader. */
export function HelpPage({ me, articles: given, initialSlug = null, onReplay, onAsk, onShowMe }: HelpPageProps) {
  const [loaded, setLoaded] = useState<HelpArticle[] | null>(given ?? null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [slug, setSlug] = useState<string | null>(initialSlug)
  const [keys, setKeys] = useState(false)

  useEffect(() => {
    if (given) { setLoaded(given); return }
    let live = true
    listHelp().then((a) => { if (live) setLoaded(a) }).catch((e) => { if (live) setLoadError(said(e, 'Help could not be read.')) })
    return () => { live = false }
  }, [given])
  useEffect(() => { setSlug(initialSlug) }, [initialSlug])

  const all = useMemo(() => loaded ?? [], [loaded])
  const sections = useMemo(() => group(all), [all])
  const needle = q.trim().toLowerCase()
  const hits = useMemo(() => (needle
    ? all.filter((a) => `${a.title} ${a.summary} ${a.body} ${a.section}`.toLowerCase().includes(needle))
    : []), [all, needle])
  const open = slug ? all.find((a) => a.slug === slug) ?? null : null

  // The address names the article, so the link can be shared; no route change is fired.
  const show = (s: string | null) => {
    setSlug(s)
    if (typeof window !== 'undefined') window.history.replaceState(null, '', hrefFor({ page: 'help', slug: s }))
  }

  const tall = 'h-16 justify-start'
  return (
    <Shell active="help" me={me} mainClassName="mx-auto flex w-full max-w-[1160px] flex-col gap-10 px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
      <section className="flex flex-wrap items-end gap-8">
        <div className="flex flex-[2_1_520px] flex-col gap-5">
          <h1 className="disp rise m-0 text-[44px] leading-none font-bold sm:text-[68px]">How can we <span className="rounded-md bg-volt px-2 text-ink">help?</span></h1>
          <label htmlFor="help-q" className="flex h-14 items-center gap-3 rounded-xl border-[1.5px] border-foreground bg-card px-[18px] shadow-ink focus-within:ring-[3px] focus-within:ring-ring/50">
            <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M13.5 13.5 18 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
            <input id="help-q" type="search" aria-label="Search Help" placeholder="Search: voices, ceilings, a line won't fit…" value={q} onChange={(e) => setQ(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-[17px] text-foreground outline-none placeholder:text-faint" autoComplete="off"
              /* the ring is the box's: focus-within: on the label above */ />
            <span className="tag text-faint" aria-live="polite">{loaded ? (needle ? `${hits.length} found` : `${all.length} articles`) : ''}</span>
          </label>
        </div>
        <div className="flex flex-[1_1_300px] flex-col gap-3">
          <button type="button" className={cn('btn volt shine', tall)} onClick={onReplay}>
            <Bolt size={18} />
            <span className="flex flex-col items-start leading-[1.2]"><span>Replay the tutorial</span><span className="tag font-medium opacity-75">3 min · sample ad · free</span></span>
          </button>
          <button type="button" className={cn('btn ink', tall)} onClick={onAsk}>
            <span aria-hidden="true" className="inline-flex h-[18px] items-center gap-0.5"><span className="h-2.5 w-[3px] rounded-sm bg-current" /><span className="h-[18px] w-[3px] rounded-sm bg-current" /><span className="h-3 w-[3px] rounded-sm bg-current" /></span>
            <span className="flex flex-col items-start leading-[1.2]"><span>Ask Voltage</span><span className="tag font-medium opacity-75">“how do I…” in any project</span></span>
          </button>
        </div>
      </section>

      {loadError && <p className="m-0 text-sm text-destructive" role="alert">{loadError}</p>}

      {needle ? (
        <section aria-label="Search results" className="flex flex-col gap-2.5">
          {hits.slice(0, 8).map((a) => (
            <button key={a.slug} type="button" className="rise grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-[10px] border-[1.5px] border-foreground bg-card px-4 py-3.5 text-left text-foreground hover:bg-sunk" onClick={() => show(a.slug)}>
              <span className="flex flex-col"><span className="disp text-[17px] font-semibold">{a.title}</span><span className="text-[13px] text-muted-foreground">{a.summary}</span></span>
              <span className="tag text-faint">{a.section} →</span>
            </button>
          ))}
          {hits.length === 0 && loaded && <div className="rounded-xl border-[1.5px] border-dashed border-line2 p-5 text-muted-foreground">Nothing matches. Ask Voltage in any project: it answers from these same articles.</div>}
        </section>
      ) : (
        <section aria-label="Help sections" aria-busy={!loaded && !loadError ? true : undefined} className="grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {!loaded && !loadError && <p className="m-0 text-muted-foreground" role="status">Loading Help…</p>}
          {sections.map((s, i) => (
            <div key={s.name} className="rise flex flex-col gap-1.5 rounded-xl border-[1.5px] border-foreground bg-card p-[18px] transition-[box-shadow,transform] duration-200 hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-ink" style={{ animationDelay: `${i * 40}ms` }}>
              <h2 className="disp m-0 mb-1 flex items-center gap-2.5 text-xl font-bold"><span className="tnum rounded bg-volt px-1.5 text-xs font-semibold text-ink">{pad2(i + 1)}</span>{s.name}</h2>
              {s.articles.map((a) => (
                <button key={a.slug} type="button" className="flex items-baseline gap-2 border-0 bg-transparent py-[5px] text-left text-sm text-foreground hover:text-muted-foreground" onClick={() => show(a.slug)}>
                  <span aria-hidden="true" className="tnum text-xs text-faint">→</span><span>{a.title}</span>
                </button>
              ))}
            </div>
          ))}
        </section>
      )}

      <section className="pane flex flex-wrap items-center gap-5 rounded-[14px] px-7 py-6">
        <div className="flex flex-[1_1_360px] flex-col gap-1">
          <span className="disp text-2xl font-bold">Still stuck?</span>
          <span className="pm">Ask Voltage in any project. Press <kbd className="tnum text-volt not-italic">?</kbd> in the editor for every shortcut.</span>
        </div>
        <button type="button" className="btn ghost" onClick={() => setKeys(true)}>Keyboard shortcuts</button>
      </section>
      <KeyboardSheet open={keys} onClose={() => setKeys(false)} />

      {open && <Reader article={open} onClose={() => show(null)} onAsk={onAsk} onShowMe={onShowMe} />}
    </Shell>
  )
}

/** The article, in a drawer on the right: Close, the words, Show me, Ask Voltage, Was this helpful. */
function Reader({ article, onClose, onAsk, onShowMe }: { article: HelpArticle; onClose: () => void; onAsk: () => void; onShowMe: (tour: string) => void }) {
  const title = useRef<HTMLHeadingElement>(null)
  const [rated, setRated] = useState<'yes' | 'no' | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null
    title.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); opener.current?.focus?.() }
  }, [onClose])
  useEffect(() => { setRated(null); title.current?.focus() }, [article.slug])

  return (
    <aside role="dialog" aria-modal="true" aria-labelledby="help-art-title" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col gap-4 overflow-auto border-l-[1.5px] border-ink bg-card p-5 text-foreground shadow-volt-lg sm:p-7">
      <div className="flex items-center gap-2.5">
        <span className="tag text-faint">{article.section}</span>
        <span className="flex-1" />
        <button type="button" className="btn sm" onClick={onClose}>Close</button>
      </div>
      <h2 id="help-art-title" ref={title} tabIndex={-1} className="disp m-0 text-[34px] leading-[1.05] font-bold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">{article.title}</h2>
      {article.summary && <p className="m-0 text-[17px] leading-relaxed">{article.summary}</p>}
      {article.body && <Markdown text={article.body} className="text-[15px] leading-relaxed" />}
      <div className="flex flex-wrap gap-2.5">
        {article.tour && <button type="button" className="btn volt sm" onClick={() => onShowMe(article.tour as string)}><Bolt />Show me</button>}
        <button type="button" className="btn sm" onClick={onAsk}>Ask Voltage about this</button>
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-2.5 border-t-[1.5px] border-line pt-4">
        <span className="text-muted-foreground">Was this helpful?</span>
        {rated
          ? <span className="text-faint" role="status">Thanks. Noted here only, for now.</span>
          : <>
            <button type="button" className="btn sm" onClick={() => setRated('yes')}>Yes</button>
            <button type="button" className="btn sm" onClick={() => setRated('no')}>No</button>
          </>}
      </div>
    </aside>
  )
}
