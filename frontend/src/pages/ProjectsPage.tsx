import { lazy, useEffect, useRef, useState } from 'react'
import { LazyPart } from '../lib/lazy'
import { track } from '../lib/analytics'
import type React from 'react'
import type { DragEvent } from 'react'
import type { Pin, ProjectFolder, ProjectSummary, ProjectTemplate, SpendSummary } from '../types'
import type { Me } from '../api'
import { ensureSample, frameUrl, getPins, getSpend, listArchivedFolders, listTemplates, setPin } from '../api'
import { templateFacts } from '../lib/templates'
import { ofCeiling } from '../lib/money'
import { hrefFor } from '../lib/route'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'
import { Shell } from './Shell'
import { FillBar } from './bits'
import { whenLabel } from './fmt'
import { MoveDialog } from '../components/MoveDialog'
import { useFlags } from '../flags/useFlags'
import { REVIEWER_NOTE, useWorkspaceRole } from '../lib/useWorkspaceRole'
import { HomeSearch } from './HomeSearch'
import { Tip } from '../guides/Tip'
import { LinkImport } from './LinkImport'

import type { Sort } from '../lib/home'
// Rehearsal item 7: language versions (phase B, off for the public) load on first use.
const LanguageChips = lazy(() => import('./LanguageVersions').then((m) => ({ default: m.LanguageChips })))
import { SORTS, STAGES, needsAttention, sortVideos } from '../lib/home'

/** A pin glyph; filled when pinned. */
const PinGlyph = ({ on }: { on: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 2h4l-.5 4 2.5 2.5V10H4V8.5L6.5 6zM8 10v4.5" fill={on ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
)

interface ProjectsPageProps {
  me: Me | null
  /** Every video, newest first (standalone and in projects). */
  projects: ProjectSummary[]
  /** The folders. */
  folders?: ProjectFolder[]
  onOpen: (id: string) => void
  /** A file to upload, into a project or standalone. */
  onUpload: (file: File, projectId: string | null) => void
  onSample: () => void
  onDelete: (id: string) => void
  /** D1: `templateId` starts the project from a template (Blank when absent). */
  onNewFolder?: (name: string, templateId?: string) => Promise<ProjectFolder | void> | void
  /** A project the Move dialog made itself: the caller only refreshes its lists. */
  onFolderMade?: (folder: ProjectFolder) => void
  /** A video moved (or made standalone): the caller refreshes its lists. */
  onMoved?: (videoId: string, projectId: string | null) => void
  /** Above the hero: the offer of the guided run to someone new. */
  banner?: React.ReactNode
  uploading: boolean
  /** How much of the upload has gone, 0..1; null while transcribing or unknown. */
  progress?: number | null
  error?: string | null
  /** How long "Deleted · Undo" waits before the delete goes through. */
  undoMs?: number
  /** G1: the sample project was just made for a new owner; the caller refreshes its lists. */
  onSampleMade?: () => void
}

// G1: Home asks for the sample project once per page load (the server makes it once ever).
let sampleAsked = false

/** This month's spend against the monthly ceiling, in the header, labelled with the month:
 *  "October: $0.14 of $100". Nothing until the summary is in. */
function MonthSpend() {
  const [spend, setSpend] = useState<SpendSummary | null>(null)
  useEffect(() => {
    let live = true
    getSpend().then((s) => { if (live) setSpend(s) }).catch(() => { /* the header just stays quiet */ })
    return () => { live = false }
  }, [])
  if (!spend) return null
  const month = spend.month
  const share = month.ceiling_usd ? month.spent_usd / month.ceiling_usd : 0
  return (
    <a href={hrefFor({ page: 'usage' })} className="inline-flex items-center gap-2 text-foreground no-underline" data-testid="month-spend" data-money-scope="month">
      <span className="tnum"><span className="font-semibold">{month.label}:</span> {ofCeiling(month)}</span>
      {month.ceiling_usd != null && <FillBar share={share} height={8} strong className="w-[52px] rounded-sm" />}
    </a>
  )
}

/** The video's first frame; a plain dark block when there is none to fetch. */
function Frame({ id }: { id: string }) {
  const [broken, setBroken] = useState(false)
  if (broken) return <span className="absolute inset-0 block bg-pic" aria-hidden="true" data-testid="frame-fallback" />
  return <img className="absolute inset-0 size-full object-cover" src={frameUrl(id, 0)} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />
}

/** A folder glyph: a small rect with a tab; dashed for "no project". */
export const Folder = ({ dashed, filled, size = 18, className }: { dashed?: boolean; filled?: boolean; size?: number; className?: string }) => (
  <span aria-hidden="true" className={cn('relative inline-block flex-none rounded-[3px] border-[1.5px] border-current', dashed && 'border-dashed', filled && 'bg-volt', className)} style={{ width: size, height: Math.round(size * 0.78) }}>
    {!dashed && <span className="absolute -top-[5px] -left-[1.5px] h-1 w-2 rounded-t-sm border-[1.5px] border-b-0 border-current" />}
  </span>
)

type Tab = 'all' | 'in' | 'none'

/** Home (folders, 2026-10-19): a sidebar of projects, the drop zone with an
 *  "Add to" picker, and the recent videos as cards with a project chip.
 *  Each card's ••• has Move to project… and Delete; deleting waits with
 *  Undo before anything goes. */
export function ProjectsPage({ me, projects, folders = [], onOpen, onUpload, onSample, onDelete, onNewFolder, onFolderMade, onMoved, banner, uploading, progress = null, error, undoMs = 5000, onSampleMade }: ProjectsPageProps) {
  const input = useRef<HTMLInputElement>(null)
  // G1: the sample project and import from a link.
  const g1 = useFlags().enabled('golive.g1')
  // Rehearsal item 7: a Reviewer watches; nothing to upload, make, move or delete.
  const flagsNow = useFlags()
  const watching = useWorkspaceRole(flagsNow.enabled('golive.g2'), flagsNow.loading) === 'reviewer'
  useEffect(() => {
    if (!g1 || sampleAsked) return
    sampleAsked = true
    ensureSample().then((r) => { if (r.created) onSampleMade?.() }).catch(() => { /* Home works without it */ })
  }, [g1, onSampleMade])
  // A1: "Brief changed" on a card whose project's brief moved on since it was made.
  const briefChips = useFlags().enabled('projects.consistency')
  // B2: a language version says its language; a master shows its versions as chips.
  const languageChips = useFlags().enabled('projects.batch')
  // D3: deleting moves to the Bin, said as such.
  const binOn = useFlags().enabled('projects.reuse')
  // D4 (projects.reuse too): pins, archived projects, search, sort and filter.
  const reuseOn = binOn
  const [pins, setPins] = useState<Pin[]>([])
  const [archived, setArchived] = useState<ProjectFolder[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [sort, setSort] = useState<Sort>('edited')
  const [stageFilter, setStageFilter] = useState('all')
  const [attention, setAttention] = useState(false)
  useEffect(() => {
    if (!reuseOn) return
    let live = true
    getPins().then((p) => { if (live) setPins(p) }).catch(() => { /* the sidebar works without pins */ })
    listArchivedFolders().then((a) => { if (live) setArchived(a) }).catch(() => { /* the filter just shows none */ })
    return () => { live = false }
  }, [reuseOn, folders])
  const isPinned = (kind: Pin['kind'], id: string) => pins.some((p) => p.kind === kind && p.id === id)
  const togglePin = async (kind: Pin['kind'], id: string, name: string) => {
    const was = pins
    const on = !isPinned(kind, id)
    track(on ? 'pin.added' : 'pin.removed', { kind })
    setPins(on ? [...was, { kind, id, name, pinned_at: new Date().toISOString() }] : was.filter((p) => !(p.kind === kind && p.id === id)))
    try { await setPin(kind, id, on) } catch {
      setPins(was)
      setToast(on ? `Could not pin ${name}.` : `Could not unpin ${name}.`)
      window.setTimeout(() => setToast(null), 5000)
    }
  }
  const [over, setOver] = useState(false)
  const [dest, setDest] = useState<string>('none')
  const [tab, setTab] = useState<Tab>('all')
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [making, setMaking] = useState(false)
  const [makeError, setMakeError] = useState<string | null>(null)
  // The project just made: first in the list, and shown as selected.
  const [selected, setSelected] = useState<string | null>(null)
  const nameInput = useRef<HTMLInputElement>(null)
  useEffect(() => { if (adding) nameInput.current?.focus() }, [adding])
  // D1 (projects.reuse): New project starts Blank or from a template.
  const [templates, setTemplates] = useState<ProjectTemplate[] | null>(null)
  const [templatesError, setTemplatesError] = useState(false)
  const [startFrom, setStartFrom] = useState('')
  useEffect(() => {
    if (!adding || !reuseOn) return
    let live = true
    setTemplatesError(false)
    listTemplates().then((t) => { if (live) setTemplates(t) }).catch(() => { if (live) setTemplatesError(true) })
    return () => { live = false }
  }, [adding, reuseOn])
  const chosen = templates?.find((t) => t.template_id === startFrom) ?? null
  const [menu, setMenu] = useState<string | null>(null)
  const [moving, setMoving] = useState<ProjectSummary | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirming) keep.current?.focus() }, [confirming])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useEffect(() => {
    if (!menu) return
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest('[data-menu]')) setMenu(null) }
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])
  // The picker follows the project list: a project deleted elsewhere falls back to standalone.
  useEffect(() => { if (dest !== 'none' && !folders.some((f) => f.project_id === dest)) setDest('none') }, [folders, dest])

  const destId = dest === 'none' ? null : dest
  const destName = destId ? folders.find((f) => f.project_id === destId)?.name ?? null : null
  const pick = () => { if (!uploading) input.current?.click() }
  const dropped = (files: FileList | null) => {
    const file = files?.[0]
    if (file && !uploading) onUpload(file, destId)
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); dropped(e.dataTransfer?.files ?? null) }
  /** Percent uploaded, or null while the size is unknown or the server is transcribing. */
  const known = progress !== null && progress < 1 ? Math.round(progress * 100) : null

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
  const cancelFolder = () => { setAdding(false); setNewName(''); setMakeError(null); setStartFrom('') }
  const makeFolder = async () => {
    const n = newName.trim()
    if (!n || !onNewFolder || making) return
    setMaking(true)
    setMakeError(null)
    try {
      const made = startFrom ? await onNewFolder(n, startFrom) : await onNewFolder(n)
      if (made) setSelected(made.project_id)
      cancelFolder()
    } catch (e) {
      setMakeError(e instanceof Error ? e.message : 'Could not make the project.')
    } finally {
      setMaking(false)
    }
  }
  // The new project leads the list until the page is left; the rest keep the server's order.
  const listed = selected ? [...folders.filter((f) => f.project_id === selected), ...folders.filter((f) => f.project_id !== selected)] : folders
  // D4: a video in an archived project is not on Home (search still finds it).
  const onHome = reuseOn ? projects.filter((p) => !p.project_archived) : projects
  const inProjects = onHome.filter((p) => p.project_id)
  const standalone = onHome.filter((p) => !p.project_id)
  const inTab = tab === 'all' ? onHome : tab === 'in' ? inProjects : standalone
  const narrowed = reuseOn ? inTab.filter((p) => (stageFilter === 'all' || (p.stage ?? 'draft') === stageFilter) && (!attention || needsAttention(p))) : inTab
  const shown = reuseOn ? sortVideos(narrowed, sort) : narrowed
  const countIn = (fid: string) => projects.filter((p) => p.project_id === fid).length

  return (
    <Shell active="projects" me={me} right={<MonthSpend />} mainClassName="flex flex-wrap">
      {/* The projects, down the side. */}
      <aside className="flex min-w-0 basis-full flex-col gap-1 border-b-[1.5px] border-line px-4 py-6 sm:flex-[0_1_260px] sm:border-r-[1.5px] sm:border-b-0" aria-label="Projects" data-testid="projects-side">
        {onNewFolder && !adding && !watching && <button type="button" className="btn volt shine mb-3.5 w-full" onClick={() => setAdding(true)}>+ New project</button>}
        {adding && (
          <form
            className="rise mb-3.5 flex w-full min-w-0 flex-col gap-2.5 rounded-lg border-[1.5px] border-foreground bg-card p-3"
            aria-label="New project"
            data-testid="new-project"
            onSubmit={(e) => { e.preventDefault(); void makeFolder() }}
            onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); cancelFolder() } }}
          >
            <label htmlFor="new-project-name" className="flex items-center gap-2.5 font-semibold"><Folder />New project</label>
            <input
              ref={nameInput}
              id="new-project-name"
              className="box-border h-10 w-full min-w-0 rounded-md border-[1.5px] border-line2 bg-background px-2.5 text-base text-foreground outline-none placeholder:text-faint focus-visible:border-ink focus-visible:ring-[3px] focus-visible:ring-volt"
              placeholder="Project name"
              value={newName}
              maxLength={80}
              disabled={making}
              onChange={(e) => setNewName(e.target.value)}
            />
            {reuseOn && (
              <div className="flex min-w-0 flex-col gap-1">
                <label htmlFor="new-project-from" className="text-[13px] font-semibold">Start from</label>
                <select id="new-project-from" className="box-border h-9 w-full min-w-0 rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm text-foreground outline-none focus-visible:border-ink focus-visible:ring-[3px] focus-visible:ring-volt"
                  value={startFrom} disabled={making || templates === null} onChange={(e) => { setStartFrom(e.target.value); if (e.target.value) track('template.start_from_picked') }} data-testid="start-from">
                  <option value="">{templates === null && !templatesError ? 'Blank (reading templates…)' : 'Blank'}</option>
                  {templates && templates.some((t) => !t.starter) && (
                    <optgroup label="Your templates">{templates.filter((t) => !t.starter).map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}</optgroup>
                  )}
                  {templates && <optgroup label="Starters">{templates.filter((t) => t.starter).map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}</optgroup>}
                </select>
                {templatesError && <span className="text-[13px] text-muted-foreground">Templates could not be read. Blank still works.</span>}
                {chosen && <span className="text-[13px] text-muted-foreground" data-testid="start-from-facts">{chosen.description ? `${chosen.description} ` : ''}{templateFacts(chosen)}. No videos.</span>}
                <a className="act self-start px-0 text-[13px]" href={hrefFor({ page: 'templates' })}>Manage templates</a>
              </div>
            )}
            {makeError && <span className="text-[13px] text-destructive" role="alert">{makeError}</span>}
            <div className="flex flex-wrap items-center gap-2">
              <button type="submit" className="btn volt sm" disabled={!newName.trim() || making} aria-busy={making || undefined}>{making ? 'Creating…' : 'Create'}</button>
              <button type="button" className="act" onClick={cancelFolder}>Cancel</button>
            </div>
          </form>
        )}
        {reuseOn && pins.length > 0 && (
          <>
            <span className="tag px-2.5 py-1.5 text-faint" id="pinned-h">Pinned</span>
            <ul className="m-0 mb-2 flex list-none flex-col gap-0.5 p-0" aria-labelledby="pinned-h" data-testid="pinned">
              {pins.map((pin) => (
                <li key={`${pin.kind}:${pin.id}`} className="group/pin flex min-w-0 items-center rounded-lg hover:bg-sunk">
                  <a href={pin.kind === 'project' ? hrefFor({ page: 'folder', projectId: pin.id }) : hrefFor({ page: 'editor', projectId: pin.id })} title={pin.name} className="flex min-w-0 flex-1 items-center gap-2.5 px-2.5 py-2 text-foreground no-underline">
                    {pin.kind === 'project' ? <Folder filled /> : <span aria-hidden="true" className="grid w-[18px] flex-none place-items-center text-muted-foreground"><svg width="12" height="12" viewBox="0 0 16 16"><path d="M4.5 2.5v11l9-5.5z" fill="currentColor" /></svg></span>}
                    <span className="min-w-0 flex-1 truncate font-medium">{pin.name}</span>
                  </a>
                  <button type="button" className="act mr-1 min-h-8 w-8 justify-center p-0 opacity-0 group-hover/pin:opacity-100 focus-visible:opacity-100 pointer-coarse:min-h-11 pointer-coarse:w-11 pointer-coarse:opacity-100" aria-label={`Unpin ${pin.name}`} onClick={() => void togglePin(pin.kind, pin.id, pin.name)}><PinGlyph on /></button>
                </li>
              ))}
            </ul>
          </>
        )}
        <span className="tag px-2.5 py-1.5 text-faint">Projects</span>
        {folders.length === 0 && <span className="px-2.5 py-1.5 text-[13px] text-muted-foreground">A project holds videos that share a brief, voices and a ceiling.</span>}
        {listed.map((f) => {
          const row = (
            <a key={f.project_id} href={hrefFor({ page: 'folder', projectId: f.project_id })} aria-current={f.project_id === selected ? 'true' : undefined} title={f.name} className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-2 text-foreground no-underline hover:bg-sunk aria-[current=true]:bg-sunk aria-[current=true]:font-semibold">
              <Folder filled={countIn(f.project_id) > 0 || f.project_id === selected} />
              <span className="min-w-0 flex-1 truncate font-medium">{f.name}</span>
              {g1 && f.sample && <span className="stamp quiet">Sample</span>}
              <span className="tnum text-xs text-faint">{f.video_count ?? countIn(f.project_id)}</span>
            </a>
          )
          if (!reuseOn) return row
          const on = isPinned('project', f.project_id)
          return (
            <div key={f.project_id} className="group/row flex min-w-0 items-center gap-0.5">
              {row}
              <button type="button" className={cn('act min-h-8 w-8 flex-none justify-center p-0 focus-visible:opacity-100 pointer-coarse:min-h-11 pointer-coarse:w-11 pointer-coarse:opacity-100', on ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100')} aria-label={on ? `Unpin ${f.name}` : `Pin ${f.name}`} aria-pressed={on} title={on ? 'Pinned to the top of Home' : 'Pin to the top of Home'} onClick={() => void togglePin('project', f.project_id, f.name)}><PinGlyph on={on} /></button>
            </div>
          )
        })}
        <span className="tag px-2.5 pt-4 pb-1.5 text-faint">Not in a project</span>
        <button type="button" className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-sunk" onClick={() => setTab('none')} aria-pressed={tab === 'none'}>
          <Folder dashed />
          <span className="flex-1 font-medium">Standalone videos</span>
          <span className="tnum text-xs text-faint">{standalone.length}</span>
        </button>
        {reuseOn && (
          <>
            <button type="button" className="mt-3 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-muted-foreground hover:bg-sunk" aria-pressed={showArchived} aria-expanded={showArchived} onClick={() => setShowArchived((v) => !v)} data-testid="archived-filter">
              <span aria-hidden="true" className="w-[18px] text-center">{showArchived ? '▾' : '▸'}</span>
              <span className="flex-1 font-medium">Archived · {archived.length}</span>
            </button>
            {showArchived && (archived.length === 0
              ? <span className="px-2.5 py-1.5 text-[13px] text-muted-foreground">No archived projects. Archive one from its page when the work is done.</span>
              : archived.map((f) => (
                <a key={f.project_id} href={hrefFor({ page: 'folder', projectId: f.project_id })} title={f.name} className="flex min-w-0 items-center gap-2.5 rounded-lg px-2.5 py-2 text-muted-foreground no-underline hover:bg-sunk">
                  <Folder />
                  <span className="min-w-0 flex-1 truncate font-medium">{f.name}</span>
                  <span className="stamp quiet">Archived</span>
                </a>
              )))}
            <a href={hrefFor({ page: 'templates' })} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-muted-foreground no-underline hover:bg-sunk" data-testid="templates-link">
              <span aria-hidden="true" className="w-[18px] text-center">▦</span>
              <span className="flex-1 font-medium">Templates</span>
            </a>
            {/* Decision 0: the Bin lives at the foot of Home's sidebar, not in the main nav. */}
            <a href={hrefFor({ page: 'bin' })} className="mt-auto flex w-full items-center gap-2.5 rounded-lg border-t border-line px-2.5 pt-4 pb-2 text-muted-foreground no-underline hover:bg-sunk" data-testid="bin-link">
              <span aria-hidden="true" className="w-[18px] text-center">⌫</span>
              <span className="flex-1 font-medium">Bin</span>
            </a>
          </>
        )}
      </aside>

      <div className="min-w-0 flex-[999_1_640px] px-4 pt-10 pb-20 sm:px-8">
        <div className="mx-auto flex max-w-[1040px] flex-col gap-10">
          {banner}
          {reuseOn && <HomeSearch />}
          {reuseOn && onHome.length > 1 && <Tip id="first-home-search" target="home-search" />}
          <section aria-labelledby="new-h" className="flex flex-col gap-[18px]">
            {watching ? (
              <>
                <h1 id="new-h" className="disp rise m-0 max-w-[820px] text-[clamp(32px,4.5vw,48px)] leading-none font-bold">Shared with you</h1>
                <p className="m-0 max-w-[640px] text-muted-foreground" data-testid="reviewer-note">{REVIEWER_NOTE}</p>
              </>
            ) : (
            <h1 id="new-h" className="disp rise m-0 max-w-[820px] text-[clamp(36px,4.5vw,56px)] leading-none font-bold">
              What should your next video <span className="rounded-md bg-volt px-2 text-ink">say?</span>
            </h1>
            )}
            {!watching && (<>
            {/* A div with real buttons, not the mock's <label>: a <button> may not sit inside a <label>. The whole zone still opens the picker. */}
            <div
              role="group"
              aria-label="Start a new video"
              aria-busy={uploading || undefined}
              data-testid="drop-zone"
              data-over={over || undefined}
              className={cn('group/drop relative flex cursor-pointer flex-wrap items-center gap-6 rounded-xl border-[1.5px] border-dashed border-foreground bg-card p-6 transition-colors hover:bg-sunk', over && 'bg-sunk')}
              onClick={(e) => { if (!(e.target as HTMLElement).closest('button,a,input,select,label')) pick() }}
              onDragOver={(e) => { e.preventDefault(); if (!uploading) setOver(true) }}
              onDragLeave={() => setOver(false)}
              onDrop={onDrop}
            >
              <span aria-hidden="true" className="grid size-14 flex-none place-items-center rounded-[14px] bg-ink text-volt motion-safe:group-hover/drop:animate-bounce">
                <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </span>
              <span className="flex flex-1 basis-[240px] flex-col gap-0.5">
                <span className="disp text-xl font-bold">Drop a video, or choose one</span>
                <span className="text-muted-foreground">Up to 10 minutes and 2 GB. It lands where you choose.</span>
              </span>
              <label className="flex flex-col gap-1">
                <span className="tag text-faint">Add to</span>
                <select className="h-10 min-w-[200px] rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground" aria-label="Add to" value={dest} onChange={(e) => setDest(e.target.value)} disabled={uploading}>
                  <option value="none">No project</option>
                  {folders.map((f) => <option key={f.project_id} value={f.project_id}>{f.name}</option>)}
                </select>
              </label>
              <span className="flex flex-wrap gap-2.5 self-end">
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
                  if (file) onUpload(file, destId)
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
            <span className="text-[13px] text-muted-foreground" data-testid="dest-note">
              {destId ? `It joins ${destName} and Voltage reads that project's brief and voices from the first turn.` : 'It will be a standalone video. You can add it to a project any time.'}
            </span>
            {g1 && <LinkImport projectId={destId} disabled={uploading} onDone={onOpen} />}
            {g1 && folders.some((f) => f.sample) && <Tip id="first-sample" target="link-import" />}
            </>)}
          </section>

          <section aria-labelledby="recent-h" className="flex flex-col gap-3.5" data-testid="recent-videos">
            <div className="flex flex-wrap items-center gap-3.5">
              <h2 id="recent-h" className="disp m-0 text-[26px] font-bold">Recent videos</h2>
              <div className="segs max-w-full flex-wrap" role="tablist" aria-label="Which videos">
                {([['all', `All · ${onHome.length}`], ['in', `In projects · ${inProjects.length}`], ['none', `No project · ${standalone.length}`]] as const).map(([k, text]) => (
                  <button key={k} type="button" role="tab" className="seg" aria-selected={tab === k} onClick={() => setTab(k)}>{text}</button>
                ))}
              </div>
            </div>
            {reuseOn && onHome.length > 0 && (
              <div className="flex flex-wrap items-center gap-2.5" data-testid="video-controls" data-tour="video-controls">
                <label className="flex items-center gap-2"><span className="tag text-faint">Sort</span>
                  <select className="h-8 rounded-lg border-[1.5px] border-foreground bg-card px-2 text-[13px] text-foreground pointer-coarse:h-11" aria-label="Sort videos" value={sort} onChange={(e) => { setSort(e.target.value as Sort); track('home.sorted', { by: e.target.value }) }}>
                    {SORTS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2"><span className="tag text-faint">Stage</span>
                  <select className="h-8 rounded-lg border-[1.5px] border-foreground bg-card px-2 text-[13px] text-foreground pointer-coarse:h-11" aria-label="Stage" value={stageFilter} onChange={(e) => { setStageFilter(e.target.value); track('home.filtered', { stage: e.target.value }) }}>
                    <option value="all">Any stage</option>
                    {STAGES.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>
                </label>
                <button type="button" className="pill" aria-pressed={attention} onClick={() => { setAttention((v) => !v); track('home.filtered', { attention: !attention }) }} title="Brief changed, out of sync with its master, or open review comments">Needs attention · {inTab.filter(needsAttention).length}</button>
              </div>
            )}
            {shown.length === 0 ? (
              <p className="m-0 text-muted-foreground">{onHome.length === 0 ? 'Your videos will show here after your first upload.' : inTab.length > 0 ? (attention && stageFilter === 'all' ? 'Nothing needs attention. Every video is current, in sync and has no open comments.' : 'No video matches. Choose Any stage or turn off Needs attention to see them all.') : tab === 'in' ? 'No video is in a project yet.' : 'Every video is in a project.'}</p>
            ) : (
              <ul className="m-0 -mx-3 grid list-none grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-2.5 p-0">
                {shown.map((p, i) => {
                  const id = p.video_id
                  return (
                    <li key={id} className="min-w-0" data-project={p.project_id ?? 'none'} data-testid="video-card">
                      {deleting === id ? (
                        <div className="flex min-h-[200px] flex-col justify-center gap-2 rounded-xl border-[1.5px] border-line2 bg-card p-4 text-[13px] text-muted-foreground" role="status">
                          <span>{binOn ? 'Moved ' : 'Deleted '}<strong className="font-semibold text-foreground">{p.filename}</strong>{binOn ? <> to the <a href={hrefFor({ page: 'bin' })} className="text-foreground">Bin</a>.</> : '.'}</span>
                          <button type="button" className="btn sm self-start" onClick={undo}>Undo</button>
                        </div>
                      ) : confirming === id ? (
                        <div className="flex min-h-[200px] flex-col justify-center gap-2 rounded-xl border-[1.5px] border-destructive bg-card p-4 text-[13px] text-muted-foreground" role="group" aria-label={`Delete ${p.filename}?`}>
                          {/* D3: a deleted video waits 30 days (F8); with the Bin on, it can be restored from there. */}
                          <span>Delete <strong className="font-semibold text-foreground">{p.filename}</strong>? {binOn ? 'It goes to the Bin for 30 days with its media and takes; restore it from there until then.' : 'It is kept for 30 days with its media and takes, then goes for good.'}{p.project_id ? ' The project and its shared voices stay.' : ''}</span>
                          <span className="flex flex-wrap gap-2">
                            <button ref={keep} type="button" className="btn sm" onClick={() => setConfirming(null)}>Keep</button>
                            <button type="button" className="btn sm border-destructive text-destructive" onClick={() => begin(id)}>{binOn ? 'Move to the Bin' : 'Delete'}</button>
                          </span>
                        </div>
                      ) : (
                        <article
                          className="group/card rise relative flex flex-col gap-2.5 rounded-xl border-[1.5px] border-transparent p-3 transition-all duration-200 hover:-translate-x-0.5 hover:-translate-y-0.5 hover:border-foreground hover:bg-card hover:shadow-ink focus-within:border-foreground"
                          style={{ animationDelay: `${Math.min(i, 6) * 80}ms` }}
                        >
                          <a href={hrefFor({ page: 'editor', projectId: id })} onClick={() => onOpen(id)} className="flex min-w-0 flex-col gap-2.5 rounded-lg text-foreground no-underline outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                            <span className="relative block aspect-[16/10] overflow-hidden rounded-[10px] border-[1.5px] border-ink bg-pic">
                              <Frame id={id} />
                              <span className="tnum absolute right-2 bottom-2 rounded bg-ink/60 px-1.5 text-xs text-ptext">{clock(p.duration)}</span>
                              {briefChips && p.brief_changed && <span className="stamp need absolute top-2 left-2" title={`${p.project_name ?? 'Its project'} has a newer brief than this video was made with`} data-testid="brief-changed">Brief changed</span>}
                            </span>
                            <span className="truncate px-0.5 font-semibold">{p.filename}{languageChips && p.language_label ? ` · ${p.language_label}` : ''}</span>
                          </a>
                          {languageChips && p.out_of_sync && <span className="stamp need self-start whitespace-nowrap" data-testid="out-of-sync">Out of sync with master</span>}
                          {languageChips && (p.languages?.length ?? 0) > 0 && <LazyPart quiet><LanguageChips languages={p.languages ?? []} className="px-0.5" /></LazyPart>}
                          <div className="flex items-center gap-2 px-0.5">
                            <span className={cn('inline-flex h-6 max-w-[60%] items-center gap-1.5 truncate rounded-full border px-2 text-xs font-medium', p.project_id ? 'border-line2 bg-card text-foreground' : 'border-dashed border-line2 text-faint')} data-testid="project-chip">
                              <Folder dashed={!p.project_id} size={12} />
                              <span className="truncate">{p.project_name ?? (p.project_id ? 'In a project' : 'No project')}</span>
                            </span>
                            <span className="flex-1" />
                            <span className="tag text-faint">{whenLabel(p.created_at)}</span>
                          </div>
                          {/* The card's menu: Move to project…, Delete. Quiet until the card is under the pointer; always there on a touch screen. */}
                          {!watching && <div className="absolute top-4 right-4" data-menu>
                            <button
                              type="button"
                              className="act bg-card/90 opacity-0 group-hover/card:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100 pointer-coarse:opacity-100"
                              aria-label={`More for ${p.filename}`}
                              aria-haspopup="menu"
                              aria-expanded={menu === id}
                              onClick={() => setMenu((m) => (m === id ? null : id))}
                            >•••</button>
                            {menu === id && (
                              <div role="menu" className="rise absolute right-0 z-10 mt-1 flex w-56 flex-col rounded-xl border-[1.5px] border-ink bg-card p-1.5 shadow-volt">
                                <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(null); setMoving(p) }}>↗ Move to project…</button>
                                {reuseOn && <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(null); void togglePin('video', id, p.filename) }}>{isPinned('video', id) ? 'Unpin from Home' : 'Pin to Home'}</button>}
                                <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(null); setConfirming(id) }}>Delete…</button>
                              </div>
                            )}
                          </div>}
                        </article>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
      {moving && (
        <MoveDialog
          video={moving}
          folders={folders}
          onClose={() => setMoving(null)}
          onFolderMade={(f) => onFolderMade?.(f)}
          onMoved={(projectId, projectName) => {
            const v = moving
            setMoving(null)
            setToast(projectId ? `Moved ${v.filename} to ${projectName}.` : `${v.filename} is now a standalone video.`)
            window.setTimeout(() => setToast(null), 5000)
            onMoved?.(v.video_id, projectId)
          }}
        />
      )}
      {toast && (
        <div role="status" className="rise fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3.5 rounded-xl bg-ink px-4 py-3 text-ptext shadow-volt">
          <span>{toast}</span>
          <button type="button" className="act text-ptext" onClick={() => setToast(null)}>Close</button>
        </div>
      )}
    </Shell>
  )
}
