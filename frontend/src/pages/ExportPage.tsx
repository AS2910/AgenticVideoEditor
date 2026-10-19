import { useEffect, useRef, useState } from 'react'
import type { ProjectDetail, Receipt } from '../types'
import type { Me } from '../api'
import { artifactUrl, createVariant, exportProject, getProject, getReceipt } from '../api'
import { go, hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { AccountDot, Bolt, Wordmark } from './Shell'
import { Tile } from './bits'
import { clockTenths, said, usd } from './fmt'

interface ExportPageProps { projectId: string; me: Me | null; onBack: () => void }

const KIND_WORD = { changed: 'Changed', added: 'Added', removed: 'Removed' } as const

/** The export as its own page: the file to download, the link, a variant, and the receipt
 *  of what went into it. Renders once if the project has no render yet. */
export function ExportPage({ projectId, me, onBack }: ExportPageProps) {
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [rendering, setRendering] = useState(false)
  const [renderSeconds, setRenderSeconds] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [variantBusy, setVariantBusy] = useState(false)
  const exported = useRef(false)
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let live = true
    exported.current = false
    setProject(null); setReceipt(null); setError(null); setRenderSeconds(null)
    const load = async () => {
      try {
        const [p, r] = await Promise.all([getProject(projectId), getReceipt(projectId)])
        if (!live) return
        setProject(p)
        if (r.render || exported.current) { setReceipt(r); return }
        // Nothing rendered yet: render once, timing it, then read the receipt again.
        exported.current = true
        setRendering(true)
        const t0 = performance.now()
        await exportProject(projectId)
        const took = Math.max(1, Math.round((performance.now() - t0) / 1000))
        const again = await getReceipt(projectId)
        if (!live) return
        setRenderSeconds(took)
        setReceipt(again)
      } catch (e) {
        if (live) setError(said(e, 'The export could not be read.'))
      } finally {
        if (live) setRendering(false)
      }
    }
    void load()
    return () => { live = false }
  }, [projectId])
  useEffect(() => () => { if (copiedTimer.current) clearTimeout(copiedTimer.current) }, [])

  const render = receipt?.render ?? null
  const url = render ? artifactUrl(projectId, render.sha256) : null
  const absolute = url && typeof window !== 'undefined' ? new URL(url, window.location.href).href : url
  const filename = project?.filename ?? ''
  const outName = render?.filename || (filename ? `${filename.replace(/\.[^.]+$/, '')}-edited.mp4` : '')
  const sameLength = render && project ? Math.abs(render.duration - project.duration) <= 0.05 : false
  const editorHref = hrefFor({ page: 'editor', projectId })

  const copy = async () => {
    if (!absolute) return
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(absolute)
      setCopied(true)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopyError(`The link could not be copied. It is ${absolute}`)
    }
  }
  const variant = async () => {
    setVariantBusy(true); setError(null)
    try {
      const p = await createVariant(projectId)
      go({ page: 'editor', projectId: p.video_id })
    } catch (e) { setError(said(e, 'The variant could not be made.')) } finally { setVariantBusy(false) }
  }

  const changes = receipt?.changes ?? []
  const n = changes.length

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex min-h-[62px] flex-wrap items-center gap-3.5 border-b-[1.5px] border-foreground bg-card px-4 py-2.5 sm:px-5">
        <Wordmark label="Voltage, all projects" />
        <span aria-hidden="true" className="text-line2">/</span>
        <a href={editorHref} className="truncate font-medium no-underline">{filename || '…'}</a>
        <span aria-hidden="true" className="text-line2">/</span>
        <span className="tag">Export</span>
        <span className="flex-1" />
        <a href={editorHref} className="tag text-muted-foreground no-underline hover:text-foreground" onClick={onBack}>← Back to editing</a>
        <AccountDot me={me} />
      </header>

      <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-wrap items-start gap-10 px-4 pt-10 pb-20 sm:gap-12 sm:px-6 sm:pt-12" aria-busy={rendering || (!receipt && !error) || undefined}>
        <section className="flex min-w-0 flex-[1_1_520px] flex-col gap-[18px]">
          <span className="tag inline-flex items-center gap-2 self-start rounded-[5px] bg-ink px-2.5 py-[5px] text-volt" role="status">
            <Bolt size={12} />{rendering ? 'Rendering…' : render ? (renderSeconds !== null ? `Rendered in ${renderSeconds} s` : 'Rendered') : error ? 'Not rendered' : 'Reading the receipt…'}
          </span>
          <h1 className="disp rise m-0 text-[clamp(48px,6vw,80px)] leading-[.95] font-bold">
            {render ? <>It's <span className="stampin rounded-md bg-volt px-2.5 text-ink">out.</span></> : rendering ? 'Nearly out.' : 'Export'}
          </h1>
          {render ? (
            <p className="m-0 max-w-[520px] text-[17px] text-muted-foreground">
              {outName} · {clockTenths(render.duration)}{sameLength ? ', the same length as the original' : ''} · H.264 + AAC · plays everywhere.
            </p>
          ) : (
            <p className="m-0 max-w-[520px] text-[17px] text-muted-foreground">{rendering ? 'Voltage is writing the file: the added lines over the picture, nothing else touched.' : error ?? 'One moment.'}</p>
          )}
          {error && render && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
          {error && !render && <p className="sr-only" role="alert">{error}</p>}

          <div className={cn('relative mt-2.5 aspect-video w-full overflow-hidden rounded-[14px] border-[1.5px] border-ink bg-pic', render && 'shadow-volt-lg')}>
            {url ? (
              <video className="block size-full bg-pic" src={url} controls playsInline preload="metadata" data-testid="render" />
            ) : (
              rendering && <span aria-hidden="true" className="scan absolute top-0 bottom-0 w-0.5 bg-volt" />
            )}
            {render && <span className="tag pointer-events-none absolute top-3.5 left-3.5 rounded-[5px] bg-ink/60 px-2 py-1 text-volt">Final</span>}
          </div>
        </section>

        <section className="flex min-w-0 flex-[1_1_380px] flex-col gap-7">
          <div className="flex flex-col gap-3">
            {url ? (
              <a href={url} download={outName || true} className="btn volt lg shine w-full">
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v9M4 7.5 8 11.5l4-4M3 14h10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                Download MP4
              </a>
            ) : (
              <button type="button" className="btn volt lg w-full" disabled>Download MP4</button>
            )}
            <div className="flex flex-wrap gap-2.5">
              <button type="button" className="btn flex-[1_1_150px]" onClick={() => void copy()} disabled={!url} aria-live="polite">{copied ? '✓ Link copied' : 'Copy link'}</button>
              <button type="button" className="btn flex-[1_1_150px]" onClick={() => void variant()} disabled={variantBusy}>{variantBusy ? 'Making…' : 'Make a variant'}</button>
            </div>
            {copyError && <p className="m-0 text-[13px] text-destructive" role="alert">{copyError}</p>}
            <span className="text-[13px] text-muted-foreground">A variant copies the clip and its plan as a draft, ready for the next version.{project?.project_name ? ` It lands in ${project.project_name} too.` : ''}</span>
          </div>

          <div className="flex flex-col">
            <div className="flex items-baseline gap-2.5 border-b-[1.5px] border-foreground pb-1.5">
              <h2 className="disp m-0 text-[22px] font-bold">In the file</h2>
              <span className="tag text-faint">{receipt ? `${n} ${n === 1 ? 'change' : 'changes'}` : '…'}</span>
            </div>
            {changes.map((c, i) => (
              <div key={c.edit_id} className="rise grid grid-cols-[70px_minmax(0,1fr)_auto] items-baseline gap-3 border-b border-line py-3" style={{ animationDelay: `${0.35 + i * 0.15}s` }}>
                <span className="tnum text-xs text-faint">{clockTenths(c.start)}</span>
                <span>{c.text}{c.note && <><br /><span className="text-[13px] text-muted-foreground">{c.note}</span></>}</span>
                <span className="stamp in">{KIND_WORD[c.kind]}</span>
              </div>
            ))}
            <div className="grid grid-cols-[70px_minmax(0,1fr)_auto] gap-3 py-3">
              <span /><span className="text-[13px] text-muted-foreground">Still a draft, not in the file: {receipt ? (receipt.drafts > 0 ? receipt.drafts : 'nothing') : '…'}.</span><span />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            <Tile label="Turns" value={receipt ? receipt.turns : '—'} size="md" className="rise" />
            <Tile label="Takes" value={receipt ? receipt.takes : '—'} size="md" className="rise d1" />
            <Tile label="Spent" value={receipt ? usd(receipt.spent_usd) : '—'} size="md" tone="volt" className="rise d1" />
          </div>
          <a href={hrefFor({ page: 'usage' })} className="tag text-muted-foreground no-underline hover:text-foreground">Full receipt →</a>
        </section>
      </main>
    </div>
  )
}
