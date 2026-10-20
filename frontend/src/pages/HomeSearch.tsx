import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { SearchHit, SearchResult } from '../types'
import { searchEverything } from '../api'
import { hrefFor } from '../lib/route'
import { hitHref } from '../lib/home'
import { clock } from '../transcript/format'
import { said } from './fmt'

const KIND_WORD: Record<SearchHit['kind'], string> = { project: 'Project', brief: 'Brief', video: 'Video', transcript: 'Said' }

/** The query's words in the hit, on volt. */
function Marked({ text, query }: { text: string; query: string }): ReactNode {
  const q = query.trim().toLowerCase()
  const at = q ? text.toLowerCase().indexOf(q) : -1
  if (at < 0) return text
  return <>{text.slice(0, at)}<mark className="rounded-sm bg-volt px-0.5 text-ink">{text.slice(at, at + q.length)}</mark>{text.slice(at + q.length)}</>
}

/** True when a key press is typing into something, so `/` must not be taken from it. */
const typing = (el: EventTarget | null) => {
  const t = el as HTMLElement | null
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
}

/** D4: search across project names, video names, what is said in each video and brief text,
 *  grouped by project. `/` focuses it (Home only: the editor keeps its own `/`); Escape clears. */
export function HomeSearch({ debounceMs = 250 }: { debounceMs?: number }) {
  const input = useRef<HTMLInputElement>(null)
  const [q, setQ] = useState('')
  const [result, setResult] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return
      e.preventDefault()
      input.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const query = q.trim()
  useEffect(() => {
    if (query.length < 2) { setResult(null); setLoading(false); setError(null); return }
    let live = true
    setLoading(true)
    setError(null)
    const t = window.setTimeout(() => {
      searchEverything(query)
        .then((r) => { if (live) { setResult(r); setLoading(false) } })
        .catch((e) => { if (live) { setError(said(e, 'Search did not work.')); setLoading(false) } })
    }, debounceMs)
    return () => { live = false; window.clearTimeout(t) }
  }, [query, debounceMs, tick])

  const clear = useCallback(() => { setQ(''); setResult(null); setError(null) }, [])
  const shown = result && result.query === query ? result : null

  return (
    <section aria-label="Search" className="flex flex-col gap-3" data-testid="home-search" data-tour="home-search">
      <label className="flex h-11 items-center gap-2.5 rounded-lg border-[1.5px] border-foreground bg-card px-3 focus-within:ring-[3px] focus-within:ring-ring/50">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="flex-none text-muted-foreground"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
        <span className="sr-only">Search projects, videos, what is said and briefs</span>
        <input
          ref={input}
          type="search"
          className="min-w-0 flex-1 bg-transparent text-base text-foreground placeholder:text-faint focus-visible:outline-none [&::-webkit-search-cancel-button]:hidden"
          placeholder="Search projects, videos, what is said, briefs"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); clear(); input.current?.blur() } }}
        />
        <span className="kbd text-muted-foreground" aria-hidden="true">/</span>
      </label>
      {query.length >= 2 && (
        <div className="rise flex flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-4" data-testid="search-results">
          {error ? (
            <div className="flex flex-wrap items-center gap-3" role="alert">
              <span className="flex-1 text-sm text-destructive">{error}</span>
              <button type="button" className="btn sm" onClick={() => setTick((n) => n + 1)}>Try again</button>
            </div>
          ) : loading || !shown ? (
            <p className="m-0 text-[13px] text-muted-foreground" role="status" aria-busy="true">Searching…</p>
          ) : shown.groups.length === 0 ? (
            <p className="m-0 text-muted-foreground" role="status">Nothing matches “{query}”. Try a word someone says in a video, or part of a project's name.</p>
          ) : (
            <>
              <span className="tag text-faint" role="status">{shown.total} {shown.total === 1 ? 'match' : 'matches'}</span>
              {shown.groups.map((g) => (
                <div key={g.project_id ?? 'none'} className="flex flex-col gap-1" data-testid={`search-group-${g.project_id ?? 'none'}`}>
                  <div className="flex items-center gap-2">
                    {g.project_id
                      ? <a href={hrefFor({ page: 'folder', projectId: g.project_id })} className="disp font-bold text-foreground no-underline hover:underline">{g.project_name}</a>
                      : <span className="disp font-bold text-muted-foreground">{g.project_name}</span>}
                    {g.archived && <span className="stamp quiet">Archived</span>}
                  </div>
                  <ul className="m-0 flex list-none flex-col p-0">
                    {g.hits.map((h, i) => (
                      <li key={`${h.kind}-${h.video_id ?? ''}-${i}`}>
                        <a href={hitHref(h, g.project_id)} className="flex min-w-0 items-baseline gap-3 rounded-lg px-2 py-1.5 text-foreground no-underline hover:bg-sunk focus-visible:bg-sunk" data-testid="search-hit">
                          <span className="tag w-[104px] flex-none whitespace-nowrap text-faint">{h.kind === 'transcript' ? `Said · ${clock(h.at ?? 0)}` : KIND_WORD[h.kind]}</span>
                          <span className="min-w-0 flex-1">
                            {(h.kind === 'transcript' || h.kind === 'brief') && h.filename && <span className="font-medium">{h.filename} · </span>}
                            <span className={h.kind === 'transcript' || h.kind === 'brief' ? 'text-muted-foreground' : 'font-medium'}><Marked text={h.text} query={query} /></span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </section>
  )
}
