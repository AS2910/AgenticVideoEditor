import { useCallback, useEffect, useState } from 'react'
import { track } from '../lib/analytics'
import type { BinItem, BinKind, BinRestored } from '../types'
import type { Me } from '../api'
import { getBin, restoreFromBin } from '../api'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { Tip } from '../guides/Tip'
import { Shell } from './Shell'
import { agoLabel } from '../lib/dates'
import { said } from './fmt'

type Filter = 'all' | BinKind
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'project', label: 'Projects' }, { key: 'video', label: 'Videos' }, { key: 'voice', label: 'Voices' },
]
const KIND_WORD: Record<BinKind, string> = { project: 'Project', video: 'Video', voice: 'Voice' }

const daysWord = (n: number) => (n <= 0 ? 'Goes today' : n === 1 ? '1 day left' : `${n} days left`)

/** Who deleted it, when, and where it goes back to: one plain line. */
function facts(item: BinItem): string {
  const who = item.deleted_by_you ? 'you' : item.deleted_by
  const parts = [`Deleted by ${who} ${agoLabel(item.deleted_at)}`]
  if (item.kind === 'project') parts.push(item.videos ? `${item.videos} ${item.videos === 1 ? 'video comes' : 'videos come'} back with it` : 'No videos were deleted with it')
  if (item.kind === 'video') {
    if (item.with_project) parts.push(`Deleted with ${item.project_name}. Restore the project to bring both back, or this alone as a standalone video`)
    else if (item.project_in_bin) parts.push(`${item.project_name} is in the Bin, so this comes back as a standalone video`)
    else if (item.project_name) parts.push(`Goes back to ${item.project_name}`)
    else if (item.project_id) parts.push('Its project is gone, so this comes back as a standalone video')
    else parts.push('A standalone video')
  }
  if (item.kind === 'voice' && item.consent) parts.push('Its consent record is kept even after the purge')
  return parts.join(' · ')
}

/** Where the restored item now is, as a sentence for the toast. */
function restoredSentence(item: BinItem, done: BinRestored): string {
  if (done.kind === 'project') {
    const n = done.videos?.length ?? 0
    return `Restored ${item.name}${n ? ` with ${n} ${n === 1 ? 'video' : 'videos'}` : ''}.`
  }
  if (done.kind === 'voice') return `Restored ${item.name}. You can pick it again.`
  if (done.standalone_because) return `Restored ${item.name}. ${done.standalone_because}`
  return done.project_name ? `Restored ${item.name} to ${done.project_name}.` : `Restored ${item.name}.`
}

const openHref = (item: BinItem, done: BinRestored) =>
  done.kind === 'project' ? hrefFor({ page: 'folder', projectId: item.id })
    : done.kind === 'video' ? hrefFor({ page: 'editor', projectId: item.id })
    : hrefFor({ page: 'voices' })

/** D3: the Bin. Deleted projects, videos and voices wait here 30 days with who deleted them,
 *  when, and the days they have left; Restore puts each back where it can go. */
export function BinPage({ me, onRestored }: { me: Me | null; onRestored?: (kind: BinKind, id: string) => void }) {
  const [items, setItems] = useState<BinItem[] | null>(null)
  const [days, setDays] = useState(30)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [busy, setBusy] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ key: string; text: string } | null>(null)
  const [toast, setToast] = useState<{ text: string; href: string } | null>(null)

  const load = useCallback(() => {
    let live = true
    setError(null)
    setItems(null)
    getBin()
      .then((b) => { if (live) { setItems(b.items); setDays(b.days) } })
      .catch((e) => { if (live) setError(said(e, 'The Bin could not be read.')) })
    return () => { live = false }
  }, [])
  useEffect(() => { track('bin.opened') }, [])
  useEffect(() => load(), [load])
  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(t)
  }, [toast])

  const keyOf = (i: BinItem) => `${i.kind}:${i.id}`
  const restore = async (item: BinItem) => {
    const key = keyOf(item)
    setBusy(key)
    setRowError(null)
    try {
      const done = await restoreFromBin(item.kind, item.id)
      // A project brings back the videos deleted with it: they leave the list too.
      const back = new Set([key, ...(done.videos ?? []).map((v) => `video:${v}`)])
      setItems((all) => (all ?? []).filter((i) => !back.has(keyOf(i))))
      setToast({ text: restoredSentence(item, done), href: openHref(item, done) })
      track('bin.restored', { kind: item.kind })
      onRestored?.(item.kind, item.id)
    } catch (e) {
      setRowError({ key, text: said(e, `${item.name} could not be restored.`) })
    } finally {
      setBusy(null)
    }
  }

  const shown = (items ?? []).filter((i) => filter === 'all' || i.kind === filter)
  const count = (k: Filter) => (items ?? []).filter((i) => k === 'all' || i.kind === k).length

  return (
    <Shell active="bin" me={me} mainClassName="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-4 pt-10 pb-20 sm:px-6 sm:pt-12">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-[1_1_300px] flex-col gap-2">
          <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Bin</h1>
          <p className="m-0 max-w-[640px] text-muted-foreground">Deleted projects, videos and voices wait here for {days} days, then go for good. What they cost stays in Usage under their names.</p>
        </div>
        <div className="segs" role="tablist" aria-label="Show">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" role="tab" className="seg" aria-selected={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label}{items ? ` · ${count(f.key)}` : ''}
            </button>
          ))}
        </div>
      </div>

      <section className="rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="bin-h" data-testid="bin-list" data-tour="bin-list">
        <h2 id="bin-h" className="sr-only">In the Bin</h2>
        {error ? (
          <div className="flex flex-wrap items-center gap-3" role="alert">
            <span className="flex-1 text-sm text-destructive">{error}</span>
            <button type="button" className="btn sm" onClick={() => load()}>Try again</button>
          </div>
        ) : items === null ? (
          <p className="m-0 min-h-[60px] text-[13px] text-muted-foreground" role="status" aria-busy="true">Reading the Bin…</p>
        ) : shown.length === 0 ? (
          <p className="m-0 text-muted-foreground" data-testid="bin-empty">
            {items.length === 0
              ? `The Bin is empty. Anything you delete waits here for ${days} days, so you can bring it back.`
              : `No ${filter === 'all' ? 'items' : FILTERS.find((f) => f.key === filter)?.label.toLowerCase()} in the Bin. Choose All to see the rest.`}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {shown.map((item) => {
              const key = keyOf(item)
              const restoring = busy === key
              return (
                <li key={key} className="rise flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line py-3.5 last:border-b-0" data-testid={`bin-${key}`}>
                  <span className="tag w-[72px] flex-none text-faint">{KIND_WORD[item.kind]}</span>
                  <span className="flex min-w-0 flex-[1_1_280px] flex-col gap-0.5">
                    <span className="truncate font-semibold" title={item.name}>{item.name}</span>
                    <span className="text-[13px] text-muted-foreground">{facts(item)}</span>
                    {rowError?.key === key && <span className="text-[13px] text-destructive" role="alert">{rowError.text}</span>}
                  </span>
                  <span className={cn('stamp whitespace-nowrap', item.days_left <= 3 ? 'need' : 'quiet')} title={`The purge removes it for good after ${days} days in the Bin`}>{daysWord(item.days_left)}</span>
                  <button type="button" className="btn sm" onClick={() => void restore(item)} disabled={busy !== null} aria-busy={restoring || undefined}
                    aria-label={`Restore ${item.name}`}>
                    {restoring ? 'Restoring…' : 'Restore'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>
      {items && items.length > 0 && <Tip id="first-bin" />}
      {toast && (
        <div role="status" className="rise fixed bottom-6 left-1/2 z-30 flex max-w-[calc(100vw-32px)] -translate-x-1/2 flex-wrap items-center gap-3.5 rounded-xl bg-ink px-4 py-3 text-ptext shadow-volt" data-testid="bin-toast">
          <span>{toast.text}</span>
          <a href={toast.href} className="btn volt sm no-underline">Open</a>
          <button type="button" className="act text-ptext" onClick={() => setToast(null)}>Close</button>
        </div>
      )}
    </Shell>
  )
}
