import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import type { ProjectSummary, UsageReport } from '../types'
import type { Me } from '../api'
import { frameUrl, getUsageReport } from '../api'
import { hrefFor } from '../lib/route'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'
import { Shell } from './Shell'
import { FillBar } from './bits'
import { firstName, greeting, monthShort, usd, usdShort, whenLabel } from './fmt'

interface ProjectsPageProps {
  me: Me | null
  projects: ProjectSummary[]
  onOpen: (id: string) => void
  onUpload: (file: File) => void
  onSample: () => void
  onDelete: (id: string) => void
  uploading: boolean
  /** How much of the upload has gone, 0..1; null while transcribing or unknown. */
  progress?: number | null
  error?: string | null
  /** How long "Deleted · Undo" waits before the delete goes through. */
  undoMs?: number
}

/** This month's spend against the ceiling, in the header; nothing until the report is in. */
function MonthSpend() {
  const [report, setReport] = useState<UsageReport | null>(null)
  useEffect(() => {
    let live = true
    getUsageReport('month').then((r) => { if (live) setReport(r) }).catch(() => { /* the header just stays quiet */ })
    return () => { live = false }
  }, [])
  if (!report) return null
  const share = report.ceiling_usd > 0 ? report.spent_usd / report.ceiling_usd : 0
  return (
    <a href={hrefFor({ page: 'usage' })} className="inline-flex items-center gap-2 text-foreground no-underline" data-testid="month-spend">
      <span className="tnum font-semibold">{usd(report.spent_usd)}</span>
      <FillBar share={share} height={8} strong className="w-[52px] rounded-sm" />
      <span className="tag text-faint">of {usdShort(report.ceiling_usd)} · {monthShort()}</span>
    </a>
  )
}

/** The project's first frame; a plain dark block when there is none to fetch. */
function Frame({ id }: { id: string }) {
  const [broken, setBroken] = useState(false)
  if (broken) return <span className="absolute inset-0 block bg-pic" aria-hidden="true" data-testid="frame-fallback" />
  return <img className="absolute inset-0 size-full object-cover" src={frameUrl(id, 0)} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />
}

const STATE_WORD: Record<NonNullable<ProjectSummary['state']>, string> = { new: 'New', draft: 'Draft', shipped: 'Exported' }

/** The start page: a greeting, the drop zone, and the recent projects as cards. Deleting
 *  asks once more in a strip across the card, then waits with Undo before anything goes. */
export function ProjectsPage({ me, projects, onOpen, onUpload, onSample, onDelete, uploading, progress = null, error, undoMs = 5000 }: ProjectsPageProps) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirming) keep.current?.focus() }, [confirming])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const name = firstName(me)
  const hour = new Date().getHours()
  const pick = () => { if (!uploading) input.current?.click() }
  const dropped = (files: FileList | null) => {
    const file = files?.[0]
    if (file && !uploading) onUpload(file)
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); dropped(e.dataTransfer?.files ?? null) }
  /** Percent uploaded, or null while the size is unknown or the server is transcribing. */
  const known = progress !== null && progress < 1 ? Math.round(progress * 100) : null

  const nameOf = (id: string) => projects.find((p) => p.project_id === id)?.filename
  const begin = (id: string) => {
    setConfirming(null)
    setDeleting(id)
    timer.current = setTimeout(() => { timer.current = null; setDeleting(null); onDelete(id) }, undoMs)
  }
  const undo = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setDeleting(null)
  }
  const secondLine = (p: ProjectSummary) =>
    p.last_change ?? (p.variant_of ? `Variant of ${nameOf(p.variant_of) ?? 'another project'}` : p.edits > 0 ? `${p.edits} ${p.edits === 1 ? 'change' : 'changes'} in the file` : 'Nothing changed yet')

  return (
    <Shell active="projects" me={me} right={<MonthSpend />} mainClassName="mx-auto flex w-full max-w-[1120px] flex-col gap-16 px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
      <section aria-labelledby="new-h" className="flex flex-col gap-6">
        <span className="tag text-faint">{name ? `${greeting(hour)}, ${name}` : 'Hello'}</span>
        <h1 id="new-h" className="disp rise m-0 max-w-[820px] text-[clamp(40px,5vw,64px)] leading-none font-bold">
          What should your next video <span className="rounded-md bg-volt px-2 text-ink">say?</span>
        </h1>
        {/* A div with real buttons, not the mock's <label>: a <button> may not sit inside a <label>. The whole zone still opens the picker. */}
        <div
          role="group"
          aria-label="Start a new video"
          aria-busy={uploading || undefined}
          data-testid="drop-zone"
          data-over={over || undefined}
          className={cn('group/drop relative flex cursor-pointer flex-wrap items-center gap-7 rounded-xl border-[1.5px] border-dashed border-foreground bg-card p-6 transition-colors hover:bg-sunk sm:p-8', over && 'bg-sunk')}
          onClick={(e) => { if (!(e.target as HTMLElement).closest('button,a,input')) pick() }}
          onDragOver={(e) => { e.preventDefault(); if (!uploading) setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <span aria-hidden="true" className="grid size-16 flex-none place-items-center rounded-[14px] bg-ink text-volt motion-safe:group-hover/drop:animate-bounce">
            <svg width="28" height="28" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <span className="flex flex-1 basis-[280px] flex-col gap-1">
            <span className="disp text-[22px] font-bold">Drop a video, or choose one</span>
            <span className="text-muted-foreground">Up to 3 minutes. With speech, or silent for a voice-over. Voltage reads it the moment it lands.</span>
          </span>
          <span className="flex flex-wrap gap-2.5">
            <button type="button" className="btn volt shine" onClick={pick} disabled={uploading}>{uploading ? 'Uploading…' : 'Choose a file'}</button>
            <button type="button" className="btn" onClick={onSample} disabled={uploading}>Try the sample ad</button>
          </span>
          <input
            ref={input}
            id="upload"
            className="sr-only"
            type="file"
            accept="video/*"
            aria-label="Choose a video"
            tabIndex={-1}
            disabled={uploading}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''   // so the same file can be picked again
              if (file) onUpload(file)
            }}
          />
          {uploading && (
            <div className="flex basis-full items-center gap-3" role="status">
              <FillBar share={known === null ? 1 : known / 100} height={8} strong className={cn('w-32', known === null && 'animate-pulse')} />
              <span className="text-[13px] text-muted-foreground">{known !== null ? `Uploading, ${known}%.` : 'Transcribing. This takes a little while for a long clip.'}</span>
            </div>
          )}
          {error && <div className="basis-full rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
        </div>
      </section>

      <section aria-labelledby="recent-h" className="flex flex-col gap-[18px]">
        <div className="flex items-baseline gap-3">
          <h2 id="recent-h" className="disp m-0 text-[26px] font-bold">Recent</h2>
          <span className="tag text-faint">{projects.length} {projects.length === 1 ? 'project' : 'projects'}</span>
        </div>
        {projects.length === 0 ? (
          <p className="m-0 text-muted-foreground">Your projects will show here after your first upload.</p>
        ) : (
          <ul className="m-0 -mx-3 grid list-none grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3 p-0">
            {projects.map((p, i) => {
              const id = p.project_id
              const state = p.state ?? 'new'
              return (
                <li key={id} className="min-w-0" data-state={state}>
                  {deleting === id ? (
                    <div className="flex min-h-[200px] flex-col justify-center gap-2 rounded-xl border-[1.5px] border-line2 bg-card p-4 text-[13px] text-muted-foreground" role="status">
                      <span>Deleted <strong className="font-semibold text-foreground">{p.filename}</strong>.</span>
                      <button type="button" className="btn sm self-start" onClick={undo}>Undo</button>
                    </div>
                  ) : confirming === id ? (
                    <div className="flex min-h-[200px] flex-col justify-center gap-2 rounded-xl border-[1.5px] border-destructive bg-card p-4 text-[13px] text-muted-foreground" role="group" aria-label={`Delete ${p.filename}?`}>
                      <span>Delete <strong className="font-semibold text-foreground">{p.filename}</strong> for good? Its media and every take go with it.</span>
                      <span className="flex flex-wrap gap-2">
                        <button ref={keep} type="button" className="btn sm" onClick={() => setConfirming(null)}>Keep</button>
                        <button type="button" className="btn sm border-destructive text-destructive" onClick={() => begin(id)}>Delete for good</button>
                      </span>
                    </div>
                  ) : (
                    <article
                      className="group/card rise relative flex flex-col gap-3 rounded-xl border-[1.5px] border-transparent p-3 transition-all duration-200 hover:-translate-x-0.5 hover:-translate-y-0.5 hover:border-foreground hover:bg-card hover:shadow-ink focus-within:border-foreground"
                      style={{ animationDelay: `${Math.min(i, 6) * 80}ms` }}
                    >
                      <a href={hrefFor({ page: 'editor', projectId: id })} onClick={() => onOpen(id)} className="flex min-w-0 flex-col gap-3 rounded-lg text-foreground no-underline outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                        <span className="relative block aspect-[16/10] overflow-hidden rounded-[10px] border-[1.5px] border-ink bg-pic">
                          <Frame id={id} />
                          <span className="tnum absolute right-2.5 bottom-2.5 rounded bg-ink/60 px-1.5 text-xs text-ptext">{clock(p.duration)}</span>
                          <span className={cn('stamp absolute top-2.5 left-2.5', state !== 'draft' && 'bg-ink/70 text-ptext')}>{STATE_WORD[state]}</span>
                        </span>
                        <span className="flex min-w-0 flex-col gap-[3px] px-0.5">
                          <span className="truncate font-semibold">{p.filename}</span>
                          <span className="truncate text-[13px] text-muted-foreground">{secondLine(p)}</span>
                          <span className="tag text-faint">{whenLabel(p.created_at)}</span>
                        </span>
                      </a>
                      {/* Quiet until the card is under the pointer; always there on a touch screen. */}
                      <button
                        type="button"
                        className="act absolute top-5 right-5 bg-card/90 opacity-0 group-hover/card:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
                        aria-label={`Delete ${p.filename}`}
                        onClick={() => setConfirming(id)}
                      >
                        Delete
                      </button>
                    </article>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </Shell>
  )
}
