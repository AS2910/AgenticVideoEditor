import { useEffect, useRef, useState } from 'react'
import type { ProjectFolder } from '../types'
import { ApiError, createFolder, moveVideo } from '../api'
import { cn } from '@/lib/utils'
import { VoiceQuestion } from './VoiceQuestion'
import { belongsTo } from '../lib/templates'

interface MoveDialogProps {
  video: { video_id: string; filename: string; project_id?: string | null; project_name?: string | null }
  folders: ProjectFolder[]
  /** The move went through: the video's new project id (or null), and its name. */
  onMoved: (projectId: string | null, projectName: string | null) => void
  onClose: () => void
  /** A project made from the dialog ("+ New project…") so the caller's list stays current. */
  onFolderMade?: (folder: ProjectFolder) => void
}

/** Move to project (folders, 2026-10-19): a dialog listing the projects and
 *  "No project"; when the video leaves a project whose voice it uses, the
 *  server answers 409 with those voices and the dialog asks once: copy the
 *  voice into this video, or keep it in your voices. Moving changes only
 *  which project the video points to. */
export function MoveDialog({ video, folders, onMoved, onClose, onFolderMade }: MoveDialogProps) {
  const current = video.project_id ?? null
  const [dest, setDest] = useState<string | null>(current)
  const [voices, setVoices] = useState<{ voice_id: string; name: string }[] | null>(null)
  const [voice, setVoice] = useState<'copy' | 'keep'>('copy')
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const first = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { first.current?.focus() }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key === 'Tab' && box.current) {
        const items = Array.from(box.current.querySelectorAll<HTMLElement>('button:not([disabled]), input, [href]'))
        if (items.length === 0) return
        const a = items[0], z = items[items.length - 1]
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus() }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus() }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const nameOf = (id: string | null) => (id ? folders.find((f) => f.project_id === id)?.name ?? id : null)
  const leaving = current !== null && dest !== current
  const label = dest === current ? 'Keep it here' : dest === null ? 'Remove from project' : `Move to ${nameOf(dest)}`
  const move = async () => {
    if (dest === current) { onClose(); return }
    setBusy(true)
    setError(null)
    try {
      await moveVideo(video.video_id, dest, voices ? voice : undefined)
      onMoved(dest, nameOf(dest))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The server names the project voices in use; the choice below answers it.
        const body = e.body as { voices?: { voice_id: string; name: string }[] } | null
        setVoices(Array.isArray(body?.voices) && body.voices.length ? body.voices : [{ voice_id: '', name: 'a project voice' }])
      } else {
        setError(e instanceof Error ? e.message : 'Could not move the video.')
      }
    } finally {
      setBusy(false)
    }
  }
  const makeFolder = async () => {
    const n = name.trim()
    if (!n) return
    setBusy(true)
    try {
      const made = await createFolder(n)
      onFolderMade?.(made)
      setDest(made.project_id)
      setNaming(false)
      setName('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make the project.')
    } finally {
      setBusy(false)
    }
  }

  const option = (id: string | null, text: string, note: string, dashed = false) => (
    <button
      key={id ?? 'none'} type="button" role="radio" aria-checked={dest === id}
      ref={id === current ? first : undefined}
      className={cn('flex w-full items-center gap-3 rounded-[10px] border-[1.5px] px-3.5 py-3 text-left transition-colors', dest === id ? 'border-ink bg-volt text-ink' : 'border-line2 bg-card hover:border-foreground')}
      onClick={() => setDest(id)}
    >
      <span aria-hidden="true" className="grid size-[18px] flex-none place-items-center rounded-full border-[1.5px] border-current">{dest === id && <span className="size-2 rounded-full bg-current" />}</span>
      <span aria-hidden="true" className={cn('h-3 w-[18px] flex-none rounded-[3px] border-[1.5px] border-current', dashed && 'border-dashed')} />
      <span className="flex-1 font-semibold">{text}</span>
      <span className="tag opacity-70">{note}</span>
    </button>
  )

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/60 p-4" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={box} role="dialog" aria-modal="true" aria-label="Move to project" className="rise flex w-full max-w-[560px] flex-col gap-4 rounded-xl border-[1.5px] border-ink bg-card p-6 shadow-volt-lg sm:px-7" data-testid="move-dialog">
        <div className="flex flex-col gap-0.5">
          <span className="tag text-faint">Move to project</span>
          <span className="disp text-[26px] font-bold">{video.filename}</span>
          <span className="text-muted-foreground">{current ? `Now in ${video.project_name ?? nameOf(current)}.` : 'Not in a project.'} Its turns, takes and edits stay with the video wherever it goes.</span>
        </div>
        <div role="radiogroup" aria-label="Destination" className="flex flex-col gap-2">
          {folders.map((f) => option(f.project_id, f.name, f.project_id === current ? 'current' : f.video_count ? `${f.video_count} ${f.video_count === 1 ? 'video' : 'videos'}` : 'empty'))}
          {option(null, 'No project', 'standalone', true)}
          {naming ? (
            <form className="flex items-center gap-2 rounded-[10px] border-[1.5px] border-foreground bg-card px-3.5 py-2" onSubmit={(e) => { e.preventDefault(); void makeFolder() }}>
              <span aria-hidden="true" className="h-3 w-[18px] flex-none rounded-[3px] border-[1.5px] border-current" />
              <input className="min-w-0 flex-1 rounded-sm bg-transparent text-base outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Name the project" placeholder="Name the project…" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
              <button type="submit" className="btn sm" disabled={busy || !name.trim()}>Make it</button>
              <button type="button" className="act" onClick={() => { setNaming(false); setName('') }}>Cancel</button>
            </form>
          ) : (
            <button type="button" className="flex w-full items-center gap-3 rounded-[10px] border-[1.5px] border-dashed border-line2 bg-card px-3.5 py-3 text-left text-muted-foreground hover:border-foreground" onClick={() => setNaming(true)}>
              <span className="w-[18px] text-center font-bold" aria-hidden="true">+</span><span>New project…</span>
            </button>
          )}
        </div>
        {voices && leaving && (
          <VoiceQuestion lead={`This video uses ${belongsTo(voices, video.project_name ?? nameOf(current) ?? '')}.`}
            copyLabel="Copy the voice into this video" value={voice} onChange={setVoice}
            note="Lines already in the video keep their audio either way. This decides whether you can still voice new lines with it." />
        )}
        {error && <div className="text-sm text-destructive" role="alert">{error}</div>}
        <div className="flex flex-wrap justify-end gap-2.5">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn volt" onClick={() => void move()} disabled={busy} aria-busy={busy || undefined}>{busy ? 'Moving…' : label}</button>
        </div>
      </div>
    </div>
  )
}
