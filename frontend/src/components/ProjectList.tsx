import { useEffect, useRef, useState } from 'react'
import type { ProjectSummary } from '../types'
import { artifactUrl } from '../api'
import { clock } from '../transcript/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/** A project's first frame, fetched only once the card is near the viewport
 *  (UX-6). Where IntersectionObserver is missing (jsdom), it mounts at once. */
function LazyFrame({ src }: { src: string }) {
  const slot = useRef<HTMLSpanElement>(null)
  const [near, setNear] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (near || !slot.current) return
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setNear(true); io.disconnect() }
    }, { rootMargin: '200px' })
    io.observe(slot.current)
    return () => io.disconnect()
  }, [near])
  return near
    ? <video className="absolute inset-0 block size-full object-cover" muted playsInline preload="metadata" tabIndex={-1} aria-hidden="true" src={src} />
    : <span ref={slot} className="absolute inset-0 block size-full" aria-hidden="true" />
}

interface ProjectListProps {
  projects: ProjectSummary[]
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  /** How long "Deleted · Undo" waits before the delete goes through. */
  undoMs?: number
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const STATE: Record<string, string> = { new: 'New', draft: 'Draft', shipped: 'Shipped' }
/** Where a project stands, in the editor's colours: drafts are what Voltage
 *  wrote (changed), shipped is kept (ok), new is neutral. */
const STATE_TONE: Record<string, string> = {
  draft: 'bg-changed-soft text-changed',
  shipped: 'bg-ok-soft text-ok',
}

/** Past projects as cards (UX-7f): a frame, the name, where each stands, and
 *  its last change. Deleting asks once more in a strip across the card, not
 *  under the finger that tapped Delete, and then waits a few seconds with
 *  Undo before anything is gone (UX-6). */
export function ProjectList({ projects, onOpen, onDelete, undoMs = 5000 }: ProjectListProps) {
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirming) keep.current?.focus() }, [confirming])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  if (projects.length === 0) {
    return <p className="m-0 text-sm text-muted-foreground">Your projects will show here after your first upload.</p>
  }
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
  return (
    <section className="flex w-full flex-col gap-3" aria-labelledby="recent-title">
      <h2 id="recent-title" className="m-0 text-xl font-semibold tracking-tight">Recent</h2>
      <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4 p-0">
      {projects.map((p) => (
        <li key={p.project_id} className="min-w-0" data-state={p.state}>
          <Card className="group/card relative min-w-0 gap-0 overflow-hidden rounded-lg p-0 transition-colors hover:border-ring/50">
          {deleting === p.project_id ? (
            <div className="flex min-h-30 flex-col justify-center gap-2 border-l-2 border-border p-4 text-sm text-muted-foreground" role="status">
              <span>Deleted <strong className="font-medium text-foreground">{p.filename}</strong>.</span>
              <Button variant="ghost" size="sm" className="self-start text-primary" onClick={undo}>Undo</Button>
            </div>
          ) : confirming === p.project_id ? (
            <div className="flex min-h-30 flex-col justify-center gap-2 border-l-2 border-destructive p-4 text-sm text-muted-foreground" role="group" aria-label={`Delete ${p.filename}?`}>
              <span>Delete <strong className="font-medium text-foreground">{p.filename}</strong> for good? Its media and every take go with it.</span>
              <span className="flex flex-wrap gap-2">
                <Button ref={keep} variant="outline" size="sm" onClick={() => setConfirming(null)}>Keep</Button>
                <Button variant="outline" size="sm" className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => begin(p.project_id)}>Delete for good</Button>
              </span>
            </div>
          ) : (
            <>
              <button className="flex w-full min-w-0 flex-col rounded-lg text-left text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50 pointer-coarse:min-h-11" onClick={() => onOpen(p.project_id)}>
                <span className="relative block aspect-video w-full overflow-hidden bg-monitor">
                  {p.media ? <LazyFrame src={`${artifactUrl(p.project_id, p.media.sha256)}#t=0.5`} /> : null}
                  <span className="tnum absolute bottom-2 left-2 rounded-md bg-background px-2 py-0.5 text-xs text-foreground shadow-xs">{clock(p.duration)}</span>
                </span>
                <span className="flex min-w-0 flex-col gap-1 px-4 pt-3 pb-4">
                  <span className="flex min-w-0 items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-semibold">{p.filename}</span>
                    {p.state && <Badge variant="secondary" className={cn(STATE_TONE[p.state])} data-state={p.state}>{STATE[p.state] ?? p.state}</Badge>}
                  </span>
                  {p.variant_of && <span className="truncate text-sm text-muted-foreground">variant{nameOf(p.variant_of) ? ` of ${nameOf(p.variant_of)}` : ''}</span>}
                  <span className="truncate text-sm text-muted-foreground">
                    {when(p.created_at)}, {p.duration.toFixed(1)} s{p.last_change ? ` · ${p.last_change}` : `, ${p.edits} ${p.edits === 1 ? 'edit' : 'edits'}`}
                  </span>
                </span>
              </button>
              {/* Delete sits in the card's corner, quiet until the card is under the pointer; always there on a touch screen. */}
              <Button
                variant="secondary"
                size="sm"
                className="absolute top-2 right-2 text-muted-foreground opacity-0 shadow-xs group-hover/card:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
                aria-label={`Delete ${p.filename}`}
                onClick={() => setConfirming(p.project_id)}
              >
                Delete
              </Button>
            </>
          )}
          </Card>
        </li>
      ))}
      </ul>
    </section>
  )
}
