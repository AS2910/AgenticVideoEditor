import { lazy, useEffect, useRef, useState } from 'react'
import { LazyPart } from '../lib/lazy'
import { track } from '../lib/analytics'
import type { DragEvent } from 'react'
import type { ProjectDetailFolder, ProjectFolder, ProjectSummary, MyVoice, MadeVoice, SpendSummary } from '../types'
import type { Me } from '../api'
import { ApiError, answerSuggestion, archiveFolder, getPins, setPin, unarchiveFolder, deleteFolder, deleteFolderFile, getFolder, getSpend, listMadeVoices, listVoices, shareVoice, unshareVoice, updateFolder, uploadFolderFile } from '../api'
import { go, hrefFor } from '../lib/route'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'
import { Shell } from './Shell'
import { formatDate } from '../lib/dates'
import { usd, usdShort } from './fmt'
import { ceilingWord } from '../lib/money'
import { FillBar, Frame } from './bits'
import { useFlags } from '../flags/useFlags'
import { REVIEWER_NOTE, useWorkspaceRole } from '../lib/useWorkspaceRole'
import { BriefHistory, BriefMeta, StaleLine } from './BriefVersions'
import { Tip } from '../guides/Tip'
import { ProjectWords } from './ProjectWords'
import type { FixRequest } from './BatchPanel'
import type { ExportPreset } from '../types'
import { STAGE_LABEL } from './feedWords'
import type { Stage } from '../types'

// Rehearsal item 7: behind flags that are off for the public (phases B, C, D and A2); loaded on first use.
const ProjectCheck = lazy(() => import('./ProjectCheck').then((m) => ({ default: m.ProjectCheck })))
const BatchPanel = lazy(() => import('./BatchPanel').then((m) => ({ default: m.BatchPanel })))
const BatchExport = lazy(() => import('./BatchExport').then((m) => ({ default: m.BatchExport })))
const ExportPresets = lazy(() => import('./ExportPresets').then((m) => ({ default: m.ExportPresets })))
const LanguageDialog = lazy(() => import('./LanguageVersions').then((m) => ({ default: m.LanguageDialog })))
const SyncChip = lazy(() => import('./LanguageVersions').then((m) => ({ default: m.SyncChip })))
const ProjectBoard = lazy(() => import('./ProjectBoard').then((m) => ({ default: m.ProjectBoard })))
const SendForReview = lazy(() => import('../review/SendForReview').then((m) => ({ default: m.SendForReview })))
const ProjectFeed = lazy(() => import('./ProjectFeed').then((m) => ({ default: m.ProjectFeed })))
const SaveTemplateDialog = lazy(() => import('./Templates').then((m) => ({ default: m.SaveTemplateDialog })))
const LearnedStyle = lazy(() => import('./LearnedStyle').then((m) => ({ default: m.LearnedStyle })))

interface ProjectPageProps {
  me: Me | null
  projectId: string
  /** A file dropped on the page goes into this project. */
  onUpload: (file: File, projectId: string) => void
  uploading?: boolean
  error?: string | null
  /** The project is gone (deleted); the caller leaves. */
  onDeleted?: () => void
}

/** C1: Grid or Board, remembered per user in this browser. */
type VideosView = 'grid' | 'board'
const viewKey = (me: Me | null) => `voltage-project-view:${me?.user?.sub ?? 'local'}`
function readView(me: Me | null): VideosView {
  try { return localStorage.getItem(viewKey(me)) === 'board' ? 'board' : 'grid' } catch { return 'grid' }
}
function keepView(me: Me | null, view: VideosView) {
  try { localStorage.setItem(viewKey(me), view) } catch { /* the choice lasts this visit only */ }
}

const STATE_WORD: Record<NonNullable<ProjectSummary['state']>, string> = { new: 'New', draft: 'Draft', shipped: 'Exported' }
const AUTONOMY_WORD: Record<string, string> = { ask: 'Check with me', draft: 'Just do it' }

/** A project (folders, 2026-10-19): its videos, and what they share — the
 *  brief Voltage reads in every turn (with its suggestions to accept), the
 *  shared voices, the reference files, the defaults and the ceiling. */
export function ProjectPage({ me, projectId, onUpload, uploading, error, onDeleted }: ProjectPageProps) {
  const [detail, setDetail] = useState<ProjectDetailFolder | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const [brief, setBrief] = useState('')
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [menu, setMenu] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [ceilingDraft, setCeilingDraft] = useState<string | null>(null)
  // Spend scopes: this project's spend and the month's, for the header.
  const [spend, setSpend] = useState<SpendSummary | null>(null)
  const [adding, setAdding] = useState(false)
  const [mine, setMine] = useState<(MyVoice | MadeVoice)[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  // A1 (projects.consistency): the brief's history, open under it.
  const [history, setHistory] = useState(false)
  const { enabled } = useFlags()
  const consistency = enabled('projects.consistency')
  // B1 (projects.batch): one goal across every video; a Fix in all from the check lands here.
  const batchOn = enabled('projects.batch')
  const [fixAll, setFixAll] = useState<FixRequest | null>(null)
  // B3 (projects.batch): the presets the Presets section holds, for the export panel.
  const [exportPresets, setExportPresets] = useState<ExportPreset[] | null>(null)
  // B2 (projects.batch): the master whose language versions are being made, and the batch board's re-read.
  const [langFor, setLangFor] = useState<ProjectSummary | null>(null)
  // C2: Send for review for the picked videos of this project.
  const [reviewing, setReviewing] = useState(false)
  const [batchTick, setBatchTick] = useState(0)
  // C1 (projects.review): Grid or Board, and the feed's re-read after a move.
  const reviewOn = enabled('projects.review')
  // D4 (projects.reuse): archive (read-only until unarchived) and pin to Home.
  const reuseOn = enabled('projects.reuse')
  // Rehearsal item 7: a Reviewer watches; the page leaves out uploads and menus and its panels are read-only.
  const watching = useWorkspaceRole(enabled('golive.g2')) === 'reviewer'
  const [pinned, setPinned] = useState(false)
  // D1 (projects.reuse): Save as template.
  const [templating, setTemplating] = useState(false)
  useEffect(() => {
    if (!reuseOn) return
    let live = true
    getPins().then((p) => { if (live) setPinned(p.some((x) => x.kind === 'project' && x.id === projectId)) }).catch(() => { /* the menu says Pin */ })
    return () => { live = false }
  }, [reuseOn, projectId])
  const [view, setView] = useState<VideosView>(() => readView(me))
  const [feedTick, setFeedTick] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const refInput = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = async () => {
    try {
      const d = await getFolder(projectId)
      setDetail(d)
      setBrief(d.project.brief)
      setName(d.project.name)
    } catch (e) {
      setMissing(e instanceof ApiError && e.status === 404 ? 'That project is gone.' : e instanceof Error ? e.message : 'Could not open the project.')
    }
  }
  useEffect(() => { void load() /* eslint-disable-line react-hooks/exhaustive-deps */ }, [projectId])
  // Spend scopes: read again when the project or its ceiling changes.
  const ceilingNow = detail?.project.ceiling_usd ?? null
  useEffect(() => {
    let live = true
    getSpend({ project: projectId }).then((s) => { if (live) setSpend(s) }).catch(() => { /* the header line stays quiet */ })
    return () => { live = false }
  }, [projectId, ceilingNow])
  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current) }, [])
  useEffect(() => {
    if (!menu) return
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest('[data-menu]')) setMenu(false) }
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])

  const project = detail?.project
  const say = (e: unknown, fallback: string) => setNote(e instanceof Error ? e.message : fallback)

  /** The brief saves itself a moment after typing stops; a change reaches every video in the project. */
  const editBrief = (text: string) => {
    setBrief(text)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null
      updateFolder(projectId, { brief: text }).then((p) => { setDetail((d) => (d ? { ...d, project: p } : d)); setSavedAt(Date.now()); if (consistency) void getFolder(projectId).then((d) => setDetail((cur) => (cur ? { ...cur, videos: d.videos } : d))).catch(() => { /* the chips catch up on the next load */ }) }).catch((e) => say(e, 'Could not save the brief.'))
    }, 600)
  }
  const rename = async () => {
    const n = name.trim()
    if (!n || !project) return
    try {
      const p = await updateFolder(projectId, { name: n })
      setDetail((d) => (d ? { ...d, project: p } : d))
      setRenaming(false)
    } catch (e) { say(e, 'Could not rename the project.') }
  }
  const remove = async (videos: 'delete' | 'keep') => {
    setBusy('delete')
    try {
      await deleteFolder(projectId, videos)
      onDeleted?.()
      go({ page: 'projects' })
    } catch (e) { say(e, 'Could not delete the project.') } finally { setBusy(null); setDeleting(false) }
  }
  const setArchivedTo = async (on: boolean) => {
    setBusy('archive')
    try {
      const p = on ? await archiveFolder(projectId) : await unarchiveFolder(projectId)
      setDetail((d) => (d ? { ...d, project: { ...d.project, archived_at: p.archived_at ?? null } } : d))
      onDeleted?.()   // Home's lists change: read them again
    } catch (e) { say(e, on ? 'Could not archive the project.' : 'Could not unarchive the project.') } finally { setBusy(null) }
  }
  const togglePin = async () => {
    const on = !pinned
    setPinned(on)
    try { await setPin('project', projectId, on) } catch (e) { setPinned(!on); say(e, 'Could not change the pin.') }
  }
  const saveCeiling = async () => {
    if (ceilingDraft === null) return
    const n = ceilingDraft.trim() === '' ? null : Number(ceilingDraft)
    if (n !== null && !(n > 0)) { setNote('A ceiling is a number of dollars, or empty for none.'); return }
    try {
      const p = await updateFolder(projectId, { ceiling_usd: n })
      setDetail((d) => (d ? { ...d, project: p } : d))
      setCeilingDraft(null)
    } catch (e) { say(e, 'Could not set the ceiling.') }
  }
  const setDefault = async (change: Partial<NonNullable<ProjectFolder['settings']>>) => {
    if (!project) return
    try {
      const p = await updateFolder(projectId, { settings: { ...(project.settings ?? { autonomy: 'ask' }), ...change } })
      setDetail((d) => (d ? { ...d, project: p } : d))
    } catch (e) { say(e, 'Could not change the default.') }
  }
  const answer = async (sid: string, what: 'accept' | 'dismiss') => {
    setBusy(sid)
    try {
      const d = await answerSuggestion(projectId, sid, what)
      setDetail(d)
      setBrief(d.project.brief)
    } catch (e) { say(e, 'Could not answer that.') } finally { setBusy(null) }
  }
  const openAdd = async () => {
    setAdding(true)
    try {
      const [v, made] = await Promise.all([listVoices(), listMadeVoices().then((r) => r.voices).catch(() => [] as MadeVoice[])])
      const have = new Set((detail?.voices ?? []).map((x) => x.voice_id))
      setMine([...(v.mine ?? []), ...made].filter((x) => !have.has(x.voice_id)))
    } catch (e) { say(e, 'Could not list your voices.') }
  }
  const share = async (voiceId: string) => {
    setBusy(voiceId)
    try {
      const voices = await shareVoice(projectId, voiceId)
      setDetail((d) => (d ? { ...d, voices } : d))
      setAdding(false)
    } catch (e) { say(e, 'Could not share that voice.') } finally { setBusy(null) }
  }
  const unshare = async (voiceId: string) => {
    setBusy(voiceId)
    try {
      await unshareVoice(projectId, voiceId)
      setDetail((d) => (d ? { ...d, voices: d.voices.filter((v) => v.voice_id !== voiceId) } : d))
    } catch (e) { say(e, 'Could not remove that voice.') } finally { setBusy(null) }
  }
  const addFile = async (file: File | undefined) => {
    if (!file) return
    setBusy('file')
    try {
      const entry = await uploadFolderFile(projectId, file)
      setDetail((d) => (d ? { ...d, files: [...d.files.filter((f) => f.sha256 !== entry.sha256), entry] } : d))
    } catch (e) { say(e, 'Could not add that file.') } finally { setBusy(null) }
  }
  const dropFile = async (sha: string) => {
    setBusy(sha)
    try {
      await deleteFolderFile(projectId, sha)
      setDetail((d) => (d ? { ...d, files: d.files.filter((f) => f.sha256 !== sha) } : d))
    } catch (e) { say(e, 'Could not remove that file.') } finally { setBusy(null) }
  }
  const chooseView = (v: VideosView) => { setView(v); keepView(me, v); if (v === 'board') track('board.opened') }
  /** C1: a card changed stage on the board (or went back after a refusal). */
  const staged = (videoId: string, stage: Stage) => {
    setDetail((d) => (d ? { ...d, videos: d.videos.map((v) => (v.video_id === videoId ? { ...v, stage } : v)) } : d))
    setFeedTick((t) => t + 1)
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); const f = e.dataTransfer?.files?.[0]; if (f && !uploading) onUpload(f, projectId) }

  if (missing) {
    return (
      <Shell active="projects" me={me} mainClassName="mx-auto flex w-full max-w-[720px] flex-col items-start gap-4 px-6 py-16">
        <p className="disp m-0 text-2xl font-bold" role="alert">{missing}</p>
        <a className="btn sm" href={hrefFor({ page: 'projects' })}>← Home</a>
      </Shell>
    )
  }
  if (!detail || !project) {
    return <Shell active="projects" me={me} mainClassName="mx-auto w-full max-w-[1200px] px-6 py-16"><p className="m-0 text-muted-foreground" role="status">Opening the project…</p></Shell>
  }
  const voiceKind: Record<string, string> = { designed: 'Designed', cloned: 'Cloned', recorded: 'Recorded', library: 'Library' }
  const ceiling = project.ceiling_usd
  const tagLine = [`${detail.videos.length} ${detail.videos.length === 1 ? 'video' : 'videos'}`, `${detail.voices.length} shared ${detail.voices.length === 1 ? 'voice' : 'voices'}`, `${detail.files.length} ${detail.files.length === 1 ? 'file' : 'files'}`].join(' · ')
  const ours = spend?.project ?? null
  const month = spend?.month ?? null

  return (
    <Shell active="projects" me={me} mainClassName="mx-auto flex w-full max-w-[1200px] flex-col gap-7 px-4 pt-9 pb-20 sm:px-6">
      <div className="flex flex-col gap-2.5">
        <a href={hrefFor({ page: 'projects' })} className="tag text-faint no-underline">← Home / Projects</a>
        <div className="flex flex-wrap items-end gap-[18px]">
          <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-1.5">
            {renaming ? (
              <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); void rename() }}>
                <input className="disp h-14 min-w-0 flex-1 rounded-lg border-[1.5px] border-foreground bg-card px-3 text-[32px] font-bold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Project name" value={name} autoFocus onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape') { setRenaming(false); setName(project.name) } }} />
                <button type="submit" className="btn sm" disabled={!name.trim()}>Save</button>
                <button type="button" className="act" onClick={() => { setRenaming(false); setName(project.name) }}>Cancel</button>
              </form>
            ) : (
              <h1 className="disp rise m-0 truncate text-[clamp(36px,5vw,56px)] leading-none font-bold">{project.name}</h1>
            )}
            <span className="tag text-muted-foreground">{tagLine}</span>
            {/* Spend scopes: this project's spend, then the month's, each named. */}
            <span className="tnum text-sm" data-money-scope="project" data-testid="project-spend">
              {usd(ours?.spent_usd ?? project.spent_usd)} spent in this project
              {month && <span data-money-scope="month"> · {usd(month.spent_usd)}{month.ceiling_usd != null ? ` of your ${ceilingWord(month.ceiling_usd)}` : ''} in {month.label}</span>}
            </span>
            {ceiling ? <FillBar share={(ours?.spent_usd ?? project.spent_usd) / ceiling} height={8} strong className="max-w-[320px]" label={`Project ${project.name}: ${usd(ours?.spent_usd ?? project.spent_usd)} of its ${ceilingWord(ceiling)} project ceiling`} /> : null}
          </div>
          {!watching && <div className="relative" data-menu>
            <button type="button" className="btn" aria-label="More for this project" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>•••</button>
            {menu && (
              <div role="menu" className="rise absolute right-0 z-10 mt-1 flex w-56 flex-col rounded-xl border-[1.5px] border-ink bg-card p-1.5 shadow-volt">
                <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); setRenaming(true) }}>Rename…</button>
                {reuseOn && <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); void togglePin() }}>{pinned ? 'Unpin from Home' : 'Pin to Home'}</button>}
                {reuseOn && <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); void setArchivedTo(!project.archived_at) }}>{project.archived_at ? 'Unarchive project' : 'Archive project'}</button>}
                {reuseOn && <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); setTemplating(true) }}>Save as template…</button>}
                <button type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); setDeleting(true) }}>Delete project…</button>
              </div>
            )}
          </div>}
          {!watching && <button type="button" className="btn volt shine" onClick={() => fileInput.current?.click()} disabled={uploading || (reuseOn && !!project.archived_at)}>{uploading ? 'Uploading…' : '+ Upload to this project'}</button>}
          <input ref={fileInput} className="sr-only" type="file" accept="video/*" aria-label="Choose a video for this project" tabIndex={-1} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onUpload(f, projectId) }} />
        </div>
        {watching && <p className="m-0 text-sm text-muted-foreground" data-testid="reviewer-note">{REVIEWER_NOTE}</p>}
        {reuseOn && project.archived_at && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border-[1.5px] border-foreground bg-sunk p-4" role="status" data-testid="archived-banner">
            <span className="stamp quiet">Archived</span>
            <span className="flex-1 text-sm">This project is archived. Unarchive it to make changes. It stays out of Home, and search still finds it.</span>
            <button type="button" className="btn sm" onClick={() => void setArchivedTo(false)} disabled={busy === 'archive'} aria-busy={busy === 'archive' || undefined}>{busy === 'archive' ? 'Unarchiving…' : 'Unarchive'}</button>
          </div>
        )}
        {reuseOn && templating && <LazyPart quiet><SaveTemplateDialog projectId={projectId} projectName={project.name} onClose={() => setTemplating(false)} /></LazyPart>}
        {deleting && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border-[1.5px] border-destructive bg-card p-4" role="group" aria-label={`Delete ${project.name}?`} data-testid="delete-project">
            <span className="flex-1 text-sm">Delete <strong>{project.name}</strong>? Its {detail.videos.length} {detail.videos.length === 1 ? 'video' : 'videos'} can go with it, or stay as standalone videos. {enabled('projects.reuse') ? 'It goes to the Bin for 30 days and can be restored from there; after that, project voices go unless kept in your voices.' : 'It is kept for 30 days, then goes for good; project voices go with it unless kept in your voices.'}</span>
            <button type="button" className="btn sm" onClick={() => setDeleting(false)} disabled={busy === 'delete'}>Keep the project</button>
            <button type="button" className="btn sm" onClick={() => void remove('keep')} disabled={busy === 'delete'}>Delete, keep the videos</button>
            <button type="button" className="btn sm border-destructive text-destructive" onClick={() => void remove('delete')} disabled={busy === 'delete'}>Delete the videos too</button>
          </div>
        )}
        {(error || note) && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error ?? note}</div>}
      </div>

      <div className="flex flex-wrap items-start gap-7">
        <section aria-label="Videos" className="flex min-w-0 flex-[999_1_560px] flex-col gap-3.5">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="disp m-0 text-2xl font-bold">Videos</h2>
            {reviewOn && (
              <div className="segs" role="group" aria-label="Show videos as" data-tour="board-toggle">
                {(['grid', 'board'] as const).map((v) => <button key={v} type="button" className="seg" aria-pressed={view === v} onClick={() => chooseView(v)}>{v === 'grid' ? 'Grid' : 'Board'}</button>)}
              </div>
            )}
            {reviewOn && <span className="flex-1" />}
            {reviewOn && <button type="button" className="btn sm" onClick={() => setReviewing(true)} disabled={detail.videos.length === 0} aria-haspopup="dialog" data-testid="send-review-open">Send for review</button>}
          </div>
          {consistency && <StaleLine projectId={projectId} count={project.stale_count ?? 0} version={project.brief_version} onChanged={() => void load()} />}
          {consistency && (project.stale_count ?? 0) > 0 && <Tip id="first-brief-changed" target="stale-line" />}
          {reviewOn && view === 'board' && (
            detail.videos.length === 0
              ? <p className="m-0 text-sm text-muted-foreground">No videos here yet. Upload one and it starts in Draft.</p>
              : <LazyPart><ProjectBoard videos={detail.videos} briefChips={consistency} syncChips={batchOn} onMoved={staged} /></LazyPart>
          )}
          {reviewOn && view === 'board' && detail.videos.length > 0 && <Tip id="first-board" target="board-toggle" />}
          <div className={cn('-mx-3 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2.5', reviewOn && view === 'board' && 'hidden')}>
            {detail.videos.filter((v) => !(batchOn && v.master_id && detail.videos.some((m) => m.video_id === v.master_id))).map((v, i) => {
              const state = v.state ?? 'new'
              // B2: a master and its language versions are one stacked card.
              const versions = batchOn ? detail.videos.filter((c) => c.master_id === v.video_id) : []
              const card = (
                <a key={v.video_id} href={hrefFor({ page: 'editor', projectId: v.video_id })} className="rise flex flex-col gap-2.5 rounded-xl border-[1.5px] border-transparent p-3 text-foreground no-underline transition-all duration-200 hover:-translate-x-0.5 hover:-translate-y-0.5 hover:border-foreground hover:bg-card hover:shadow-ink focus-visible:border-foreground" style={{ animationDelay: `${Math.min(i, 6) * 80}ms` }}>
                  <span className="relative block aspect-[16/10] overflow-hidden rounded-[10px] border-[1.5px] border-ink bg-pic">
                    <Frame id={v.video_id} />
                    <span className={cn('stamp absolute top-2 left-2', state !== 'draft' && 'bg-ink/70 text-ptext')}>{v.last_change && /proposed/i.test(v.last_change) ? v.last_change : STATE_WORD[state]}</span>
                    <span className="tnum absolute right-2 bottom-2 rounded bg-ink/60 px-1.5 text-xs text-ptext">{clock(v.duration)}</span>
                    {consistency && v.brief_changed && <span className="stamp need absolute top-2 right-2" title={`Made with brief v${v.made_with_brief ?? 0}; the project is on v${project.brief_version}`} data-testid="brief-changed">Brief changed</span>}
                  </span>
                  <span className="truncate font-semibold">{v.filename}{batchOn && v.language_label ? ` · ${v.language_label}` : ''}</span>
                  <span className="truncate text-[13px] text-muted-foreground">{v.last_change ?? (v.edits > 0 ? `${v.edits} ${v.edits === 1 ? 'change' : 'changes'} in the file` : 'Nothing changed yet')}</span>
                </a>
              )
              if (!batchOn) return card
              return (
                <div key={v.video_id} className={cn('flex flex-col', versions.length > 0 && 'm-1.5 rounded-xl border-[1.5px] border-foreground bg-card')} data-testid="video-stack">
                  {card}
                  {versions.length > 0 && (
                    <ul className="m-0 flex list-none flex-col gap-1.5 border-t border-line px-3 py-2.5" aria-label={`Language versions of ${v.filename}`} data-testid="language-versions" data-tour="language-versions">
                      {versions.map((c) => (
                        <li key={c.video_id} className="flex flex-wrap items-center gap-2">
                          <a className="stamp in whitespace-nowrap no-underline" href={hrefFor({ page: 'editor', projectId: c.video_id })} aria-label={`Open the ${c.language_label} version`}>{c.language_label}</a>
                          {c.out_of_sync ? <LazyPart quiet><SyncChip videoId={c.video_id} compact onStarted={() => void load()} onSettled={() => void load()} /></LazyPart> : <span className="tag text-faint">In step</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                  {!v.master_id && <button type="button" className="act mx-3 mb-2 self-start" onClick={() => setLangFor(v)} data-testid="make-languages">+ Language versions</button>}
                </div>
              )
            })}
            {!watching && <div
              role="group" aria-label="Drop a video here" data-over={over || undefined}
              className={cn('m-3 grid min-h-[200px] cursor-pointer place-items-center rounded-xl border-[1.5px] border-dashed border-foreground p-5 text-center text-muted-foreground transition-colors hover:bg-sunk', over && 'bg-sunk')}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => { e.preventDefault(); if (!uploading) setOver(true) }} onDragLeave={() => setOver(false)} onDrop={onDrop}
            >
              <span><span className="disp block text-lg font-bold text-foreground">Drop a video here</span>It joins {project.name} with its brief and voices.</span>
            </div>}
          </div>
          {batchOn && <LazyPart><BatchPanel projectId={projectId} videos={detail.videos} fix={fixAll} onFixHandled={() => setFixAll(null)} refresh={batchTick} onAdded={() => { void load(); setFeedTick((t) => t + 1) }} /></LazyPart>}
          {batchOn && <LazyPart><BatchExport projectId={projectId} presets={exportPresets} /></LazyPart>}
          {consistency && enabled('projects.check') && <LazyPart><ProjectCheck projectId={projectId} briefVersion={project.brief_version}
            onFixAll={batchOn ? (issue) => { setFixAll({ issueId: issue.issue_id, message: issue.message, videoIds: [...new Set(issue.places.map((p) => p.video_id))] }); document.querySelector('[data-testid="batch"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) } : undefined} /></LazyPart>}
          {consistency && <ProjectWords projectId={projectId} languages={batchOn} />}
          {batchOn && langFor && (
            <LazyPart quiet><LanguageDialog videoId={langFor.video_id} filename={langFor.filename} projectId={projectId} onClose={() => setLangFor(null)}
              onMade={() => { setLangFor(null); setBatchTick((t) => t + 1); void load(); document.querySelector('[data-testid="batch"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} /></LazyPart>
          )}
          {batchOn && detail.videos.some((v) => v.out_of_sync) && <Tip id="first-language-sync" target="out-of-sync" />}
          {reviewOn && reviewing && (
            <LazyPart quiet><SendForReview
              target={{ kind: 'project', projectId, title: project.name, videos: detail.videos.map((v) => ({ video_id: v.video_id, filename: v.filename, stage_label: STAGE_LABEL[v.stage as keyof typeof STAGE_LABEL] })) }}
              onClose={() => setReviewing(false)} onSent={() => { void load(); setFeedTick((t) => t + 1) }} /></LazyPart>
          )}
        </section>

        <aside aria-label="Shared with every video" className="flex min-w-0 flex-[1_1_340px] flex-col gap-3.5">
          {/* A Reviewer reads these panels; every control in them is off. */}
          <fieldset disabled={watching} className="contents">
          <div className="rise flex flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[18px] shadow-volt-lg" data-testid="brief">
            <div className="flex flex-wrap items-center gap-2"><span className="disp text-xl font-bold">Brief</span><span className="tag text-faint">Voltage reads this in every turn</span><span className="flex-1" />{savedAt && <span className="tag text-faint" role="status">Saved</span>}</div>
            {consistency && <BriefMeta project={project} me={me} open={history} onHistory={() => setHistory((h) => !h)} />}
            <label htmlFor="brief" className="sr-only">Project brief</label>
            <textarea id="brief" rows={5} className="w-full resize-y rounded-lg border-[1.5px] border-line2 bg-background p-3 text-[14.5px] leading-[1.55] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={brief} placeholder="What every video here should know: the brand and how it is said, the offer, the tone." onChange={(e) => editBrief(e.target.value)} />
            {consistency && history && <BriefHistory projectId={projectId} me={me} current={project.brief_version} onClose={() => setHistory(false)} />}
            {detail.suggestions.map((s) => (
              <div key={s.id} className="rise flex flex-col gap-2 rounded-lg bg-pane p-3 text-ptext" data-testid="suggestion">
                <span className="tag text-volt">Voltage suggests adding</span>
                <span className="text-sm">“{s.text}”{s.filename ? ` It came up in ${s.filename} and applies to every video.` : ''}{s.why ? ` ${s.why}` : ''}</span>
                <div className="flex gap-2"><button type="button" className="btn volt sm" onClick={() => void answer(s.id, 'accept')} disabled={busy === s.id}>Add to brief</button><button type="button" className="btn ghost sm" onClick={() => void answer(s.id, 'dismiss')} disabled={busy === s.id}>Not now</button></div>
              </div>
            ))}
          </div>

          {reuseOn && <LazyPart><LearnedStyle projectId={projectId} onProject={(p) => { setDetail((d) => (d ? { ...d, project: p } : d)); setBrief(p.brief) }} /></LazyPart>}

          {reviewOn && <LazyPart><ProjectFeed projectId={projectId} tick={feedTick} nameOf={(id) => detail.videos.find((v) => v.video_id === id)?.filename ?? null} /></LazyPart>}

          <div className="rise d1 flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="shared-voices">
            <div className="flex items-center gap-2"><span className="disp text-xl font-bold">Shared voices</span><span className="flex-1" /><button type="button" className="btn sm" onClick={() => void openAdd()} aria-expanded={adding}>+ Add</button></div>
            {detail.voices.length === 0 && !adding && <span className="text-[13px] text-muted-foreground">Share one of your voices and every video here can ask for it by name.</span>}
            {detail.voices.map((v) => (
              <div key={v.voice_id} className="flex items-start gap-2.5 border-t border-line py-2" data-testid="shared-voice">
                {/* Bug 2: the name keeps its own line; kind and consent sit under it, so neither can squeeze it to nothing. */}
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate font-semibold" title={v.name}>{v.name}</span>
                  <span className="text-[13px] text-muted-foreground">
                    {voiceKind[v.kind ?? 'recorded'] ?? v.kind}
                    {' · '}
                    {v.consent_needed === false ? 'No consent needed' : v.consent_granted_at ? `Consent ${formatDate(v.consent_granted_at)}${v.consent_approximate ? ' (approx.)' : ''}` : 'Consent not recorded'}
                    {v.used_in ? ` · ${v.used_in} ${v.used_in === 1 ? 'video' : 'videos'}` : ''}
                  </span>
                </div>
                <button type="button" className="act flex-none" onClick={() => void unshare(v.voice_id)} disabled={busy === v.voice_id} aria-label={`Remove ${v.name} from the project`}>Remove</button>
              </div>
            ))}
            {adding && (
              <div className="flex flex-col gap-1.5 rounded-lg bg-sunk p-2.5" role="group" aria-label="Your voices">
                {mine.length === 0 && <span className="text-[13px] text-muted-foreground">Nothing to share yet. Keep a voice on the Voices page first.</span>}
                {mine.map((v) => (
                  <button key={v.voice_id} type="button" className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-card" onClick={() => void share(v.voice_id)} disabled={busy === v.voice_id}>
                    <span className="flex-1 truncate font-medium">{v.name}</span><span className="tag text-faint">{'kind' in v && v.kind ? voiceKind[v.kind] ?? v.kind : ''}</span>
                  </button>
                ))}
                <button type="button" className="act self-start" onClick={() => setAdding(false)}>Close</button>
              </div>
            )}
          </div>

          <div className="rise d2 flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="files">
            <div className="flex items-center gap-2"><span className="disp text-xl font-bold">Reference files</span><span className="flex-1" /><button type="button" className="btn sm" onClick={() => refInput.current?.click()} disabled={busy === 'file'}>{busy === 'file' ? 'Adding…' : '+ Add'}</button></div>
            <input ref={refInput} className="sr-only" type="file" aria-label="Choose a reference file" tabIndex={-1} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; void addFile(f) }} />
            {detail.files.length === 0 && <span className="text-[13px] text-muted-foreground">A script, a brand guide, a clip of how the name is said. Voltage can read them.</span>}
            {detail.files.map((f) => (
              <div key={f.sha256} className="flex items-center gap-2.5 border-t border-line py-2">
                <span className="tnum text-xs text-faint uppercase">{f.kind}</span>
                <span className="flex-1 truncate">{f.name}</span>
                <button type="button" className="act" onClick={() => void dropFile(f.sha256)} disabled={busy === f.sha256} aria-label={`Remove ${f.name}`}>Remove</button>
              </div>
            ))}
          </div>

          {batchOn && <LazyPart><ExportPresets projectId={projectId} onChanged={setExportPresets} /></LazyPart>}

          <div className="rise d3 flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="defaults">
            <span className="disp text-xl font-bold">Defaults for new videos</span>
            <div className="flex items-center gap-2.5 border-t border-line py-2">
              <span className="flex-1">How much Voltage may do</span>
              <div className="segs" role="group" aria-label="How much Voltage may do">
                {(['ask', 'draft'] as const).map((a) => <button key={a} type="button" className="seg" aria-pressed={(project.settings?.autonomy ?? 'ask') === a} onClick={() => void setDefault({ autonomy: a })}>{AUTONOMY_WORD[a]}</button>)}
              </div>
            </div>
            <div className="flex items-center gap-2.5 border-t border-line py-2">
              <span className="flex-1">Money per turn</span>
              <label className="flex items-center gap-1.5"><span className="sr-only">Money per turn, dollars</span><span className="tnum">$</span>
                <input className="tnum h-8 w-20 rounded-md border-[1.5px] border-line2 bg-background px-2 text-right outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" type="number" step="0.1" min="0.1" defaultValue={(project.settings?.turn_usd ?? 0.5).toFixed(2)} aria-label="Money per turn" onBlur={(e) => { const n = Number(e.target.value); if (n > 0 && n !== project.settings?.turn_usd) void setDefault({ turn_usd: n }) }} />
              </label>
            </div>
            <div className="flex items-center gap-2.5 border-t border-line py-2" data-money-scope="project">
              <span className="flex-1">Project ceiling</span>
              {ceilingDraft === null ? (
                <button type="button" className="act tnum font-semibold" onClick={() => setCeilingDraft(ceiling ? String(ceiling) : '')} aria-label="Change the project ceiling">{ceiling ? `${usd(project.spent_usd)} / ${usdShort(ceiling)}` : 'None · set one'}</button>
              ) : (
                <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); void saveCeiling() }}>
                  <span className="tnum">$</span>
                  <input className="tnum h-8 w-20 rounded-md border-[1.5px] border-line2 bg-background px-2 text-right outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" type="number" step="1" min="0" value={ceilingDraft} aria-label="Project ceiling, dollars; empty for none" autoFocus onChange={(e) => setCeilingDraft(e.target.value)} />
                  <button type="submit" className="btn sm">Set</button>
                  <button type="button" className="act" onClick={() => setCeilingDraft(null)}>Cancel</button>
                </form>
              )}
            </div>
            <span className="text-[13px] text-muted-foreground">Each video keeps its own settings; these are what a new one starts with. The lowest ceiling wins.</span>
          </div>
          </fieldset>
        </aside>
      </div>
    </Shell>
  )
}
