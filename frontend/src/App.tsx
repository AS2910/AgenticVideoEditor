import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { ConsentSheet } from './components/ConsentSheet'
import { SignIn } from './components/SignIn'
import { ShipSheet } from './components/ShipSheet'
import type { Shipped } from './components/ShipSheet'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import type { Block } from './components/Player'
import { captionAt, takeCaption } from './transcript/caption'
import type { CaptionPending } from './transcript/caption'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { ExportBar } from './components/ExportBar'
import { ProjectList } from './components/ProjectList'
import { SpendMeter } from './components/SpendMeter'
import { LineDoc } from './components/LineDoc'
import type { LineRequest, PendingLine } from './components/LineDoc'
import type { LineKey } from './transcript/keys'
import { PlanCard } from './components/PlanCard'
import { ActivityLog } from './components/ActivityLog'
import { ReadingCard } from './components/ReadingCard'
import { AutonomySwitch } from './components/AutonomySwitch'
import { WhatVoltageMayDo } from './components/WhatVoltageMayDo'
import type { MayDo } from './components/WhatVoltageMayDo'
import { Presence } from './components/Presence'
import { ThemeToggle } from './components/ThemeToggle'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ArrowUp, AudioLines, ChevronLeft, ChevronRight, Film, FolderOpen, Loader2, Mic, ShieldCheck, SlidersHorizontal, Users, Zap } from 'lucide-react'
import { Lanes } from './components/Lanes'
import { VoicesSheet } from './components/VoicesSheet'
import { SpeakersBar } from './components/SpeakersBar'
import { clock } from './transcript/format'
import { speakerSlot } from './transcript/speakers'
import {
  createProject, confirmPlace, exportProject, artifactUrl, pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject, getUsage, listVoices, updateSpeaker, detectSpeakers, revertEdit, updateSettings, removeLine, dismissItem, setEditLevel, setCandidateLevel, BACKGROUND_DB, uploadMyVoice, deleteMyVoice, moveCandidate, moveEdit, shiftLine, getPlan, approvePlan, readProject, grantConsent, createVariant, getMe, logout, postTurn, getMessages,
} from './api'
import type { Me, PlanApproval } from './api'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage,
  Insert, ProjectSummary, Usage, Statement, Voice, Revision,
  Plan, PlanItem, Autonomy, Reading, Piece, ProjectDetail, ApprovedEditSummary, MyVoice,
} from './types'
import { piecesFromInserts, renderTimeFrom, sourceTimeFrom } from './timeline/selection'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'

type Stage = 'load' | 'editor'

// What Voltage may do until the project says otherwise (the server's defaults).
const MAY_DO: MayDo = { autonomy: 'ask', turn_usd: 0.5, effort: 'high', ceiling_usd: 2 }

export default function App() {
  const [stage, setStage] = useState<Stage>('load')
  // Phase 9c: whether sign-in is on, and who is here. Null until asked.
  const [me, setMe] = useState<Me | null>(null)
  const [signedOut, setSignedOut] = useState(false)
  // Consent is asked once per project, the first time a voice is about to be
  // made (UX-3): the sheet, and what to do once it is given.
  const [consentAsk, setConsentAsk] = useState<{ who: string | null; go: () => void } | null>(null)
  const [consenting, setConsenting] = useState(false)
  // Read by closures made before consent was given, so the action they
  // resume does not ask a second time.
  const consentGiven = useRef(false)
  // What just shipped, for the sheet that says what is in the file.
  const [shipped, setShipped] = useState<Shipped | null>(null)
  const [varianting, setVarianting] = useState(false)
  const [loading, setLoading] = useState(false)
  const [project, setProject] = useState<Project | null>(null)
  const [transcript, setTranscript] = useState<Word[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [segments, setSegments] = useState<Segment[]>([])
  const [inserts, setInserts] = useState<Insert[]>([])
  // Phase 16: the render as pieces — copies, flexed lines, living holds, held frames — for the clocks.
  const [pieces, setPieces] = useState<Piece[]>([])
  const [download, setDownload] = useState<{ url: string; filename: string } | null>(null)
  const [exporting, setExporting] = useState(false)
  // UX-6: how much of the upload has gone, 0..1; null when not uploading.
  const [uploadShare, setUploadShare] = useState<number | null>(null)
  // The latest render of the approved edits, and which version the player shows.
  const [rendered, setRendered] = useState<{ url: string; duration: number } | null>(null)
  // 20e: what plays — the original, the final (the added lines), or with the proposals mixed in.
  const [view, setView] = useState<'original' | 'final' | 'proposals'>('original')
  // The preview render with the proposals, keyed by the takes it carries (stale when they change).
  const [preview, setPreview] = useState<{ url: string; duration: number; pieces: Piece[]; key: string } | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  // 20i: your own voices, uploaded under a name; offered first wherever a voice is picked.
  const [myVoices, setMyVoices] = useState<MyVoice[]>([])
  const [voicesOpen, setVoicesOpen] = useState(false)
  const asVoice = (v: MyVoice): Voice => ({ voice_id: v.voice_id, name: v.name, description: 'your voice', gender: null, accent: null, age: null, category: 'mine' })
  const takeInVoices = (r: { voices: Voice[]; mine?: MyVoice[] }) => {
    setMyVoices(r.mine ?? [])
    setVoices([...(r.mine ?? []).map(asVoice), ...r.voices])
  }
  const [seekRequest, setSeekRequest] = useState<{ time: number; id: number; play?: boolean; until?: number } | null>(null)
  const [detecting, setDetecting] = useState(false)
  // Approved edits still in force, shown as tracked changes in the transcript.
  const [approved, setApproved] = useState<Revision[]>([])
  // The agent (Phase 13): how much it does on its own, and its latest plan.
  const [autonomy, setAutonomy] = useState<Autonomy>('ask')
  const [mayDo, setMayDo] = useState<MayDo>(MAY_DO)
  const [mayDoOpen, setMayDoOpen] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  // Voltage's first look at the clip (UX-2), for the goal stage.
  const [reading, setReading] = useState<Reading | null>(null)
  const [readingBusy, setReadingBusy] = useState(false)
  const readFor = useRef<string | null>(null)
  // A fresh project gets read once it opens; one with a plan or edits does not.
  const wantReading = useRef(false)
  // UX-7c: Voltage's panel can be tucked away to a rail; `\` toggles it.
  const [panelHidden, setPanelHidden] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 960px)').matches)
  const panelRef = useRef<HTMLElement>(null)
  const showPanel = () => { setPanelHidden(false); window.setTimeout(() => panelRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' }), 0) }
  // An example picked from Voltage's first message, put into the composer.
  const [seed, setSeed] = useState<{ text: string; id: number } | null>(null)
  // Phase 20: a turn of Voltage with tools is running; its latest step.
  const [turnBusy, setTurnBusy] = useState(false)
  const [turnStep, setTurnStep] = useState<string | null>(null)
  const seenSeq = useRef(0)
  // While Voltage reads, the transcript line it is "on" is lit in turn.
  // The line open in the hands-on editor, so the panel can stand by.
  const [editingLine, setEditingLine] = useState<Statement | null>(null)
  const [showPlanWhileEditing, setShowPlanWhileEditing] = useState(false)
  // The take playing in place of the line, with its own audio under the video.
  const [playingTake, setPlayingTake] = useState<string | null>(null)
  const takeAudio = useRef<HTMLAudioElement | null>(null)
  // The take playing in place, whole: its words light up as they are said (the polish pass).
  const playingCandidate = useRef<Candidate | null>(null)
  // What the phone's strip composer holds while Voltage is tucked away.
  const [railText, setRailText] = useState('')
  // The word timeline is for exact spans; hidden until asked for.
  const [precise, setPrecise] = useState(false)
  // A take or kept line being dragged to a new start on the bar.
  const [placing, setPlacing] = useState<{ id: string; start: number; duration: number } | null>(null)
  const composerRef = useRef<HTMLInputElement>(null)

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await listProjects())
    } catch {
      setProjects([]) // the list is a convenience; uploading still works
    }
  }, [])

  useEffect(() => {
    if (stage === 'load') void refreshProjects()
  }, [stage, refreshProjects])

  // Who is here (Phase 9c), then — a reload keeps you in the project you
  // had open: its id is the URL hash.
  useEffect(() => {
    getMe()
      .then((m) => {
        setMe(m)
        const id = window.location.hash.slice(1)
        if ((m.mode === 'off' || m.user) && /^p\d+$/.test(id)) void openProject(id)
      })
      .catch(() => setMe({ mode: 'off', user: null }))   // an older server: open as before
    // Only on first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A 401 anywhere means the session ended: back to the door.
  useEffect(() => {
    if (me?.mode === 'google' && error === 'Sign in to continue.') setSignedOut(true)
  }, [error, me])

  const signOut = async () => {
    try { await logout() } catch { /* the cookie is gone either way */ }
    clearEditor()
    window.location.hash = ''
    setMe((m) => (m ? { ...m, user: null } : m))
    setStage('load')
  }

  /** Back to a blank editor state, e.g. before opening another project. */
  const clearEditor = () => {
    setProject(null)
    setTranscript([])
    setSelection(null)
    setCurrentTime(0)
    setMessages([])
    setSegments([])
    setInserts([])
    setPieces([])
    setDownload(null)
    setRendered(null)
    setView('original')
    setPreview(null)
    setError(null)
    setUsage(null)
    setApproved([])
    setAutonomy('ask')
    setMayDo(MAY_DO)
    setMayDoOpen(false)
    setPlan(null)
    setReading(null)
    setReadingBusy(false)
    setShipped(null)
    setConsentAsk(null)
    consentGiven.current = false
    setEditingLine(null)
    setPlayingTake(null)
    setPlacing(null)
    takeAudio.current?.pause()
  }

  // "/" puts the cursor in the box, from anywhere that is not already typing (UX-4).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      const box = composerRef.current
      if (box) { e.preventDefault(); box.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // "\" hides Voltage to a rail and brings it back (UX-7c), from anywhere that is not typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '\\' || e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      e.preventDefault()
      setPanelHidden((h) => !h)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const projectId = project?.project_id ?? null

  /** Re-reads what the project has spent; after anything that may have paid. */
  const refreshUsage = useCallback(async (id: string | null) => {
    if (!id) return
    try {
      setUsage(await getUsage(id))
    } catch {
      // The meter is informational; a failed read leaves the last value.
    }
  }, [])

  useEffect(() => { void refreshUsage(projectId) }, [projectId, refreshUsage])

  // The voices, once: they don't change while the app is open.
  useEffect(() => {
    if (stage !== 'editor' || voices.length > 0) return
    listVoices()
      .then(takeInVoices)
      .catch(() => {}) // without the list, the editor offers no voice to pick
  }, [stage, voices.length])

  // When a fresh project opens, Voltage takes the clip in once: an opening
  // line and a role for each speaker (UX-2), as its first message (UX-7c).
  useEffect(() => {
    if (stage !== 'editor' || !projectId || !wantReading.current || reading || readFor.current === projectId) return
    readFor.current = projectId
    setReadingBusy(true)
    readProject(projectId)
      .then((r) => setReading(r))
      .catch(() => {})   // the stage still works with the plain count
      .finally(() => { setReadingBusy(false); void refreshUsage(projectId) })
  }, [stage, projectId, reading, project?.statements?.length, refreshUsage])

  /** Into the project: fresh ones start by asking what the video should
   *  say; ones with a plan or edits open straight in the editor. */
  const takeIn = (loaded: Project, edited = false) => {
    setProject(loaded)
    consentGiven.current = loaded.consent !== null && loaded.consent !== undefined
    setTranscript(loaded.transcript)
    setAutonomy(loaded.settings?.autonomy ?? 'ask')
    setMayDo({ autonomy: loaded.settings?.autonomy ?? 'ask', turn_usd: loaded.settings?.turn_usd ?? MAY_DO.turn_usd,
      effort: loaded.settings?.effort ?? MAY_DO.effort, ceiling_usd: loaded.settings?.ceiling_usd ?? MAY_DO.ceiling_usd })
    setPlan(loaded.plan ?? null)
    setReading(loaded.reading ?? null)
    // The thread's high-water mark belongs to this project: a fresh upload after
    // another project starts at zero, or its first replies would be skipped.
    seenSeq.current = Math.max(0, ...((loaded as Partial<ProjectDetail>).messages ?? []).map((m) => m.seq ?? 0))
    // UX-7c: one workspace. A fresh project is read on arrival (a clip with
    // no speech is looked at); one with a plan or edits opens as it was.
    wantReading.current = !loaded.plan && !edited
    setStage('editor')
    window.location.hash = loaded.project_id
  }

  const load = async (file: File) => {
    setLoading(true)
    setUploadShare(0)
    setError(null)
    try {
      takeIn(await createProject(file, false, setUploadShare))
    } catch (e) {
      // The backend's rejection reason is the useful part — show it verbatim.
      setError(e instanceof ApiError ? e.message : 'Could not upload that video.')
    } finally {
      setLoading(false)
      setUploadShare(null)
    }
  }

  const loadSample = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(SAMPLE_URL)
      const blob = await res.blob()
      await load(new File([blob], 'sample-ad.mp4', { type: 'video/mp4' }))
    } catch {
      setError('Could not load the sample clip.')
      setLoading(false)
    }
  }

  const say = (message: ChatMessage) => setMessages((m) => [...m, message])
  /** A failure in the plan or the conversation is Voltage's reply, in the thread,
   *  where it was asked (UX-6); the strip under the player is for the engine. */
  const tell = (text: string) => say({ role: 'assistant', text })

  /** Run `go` once the project's consent is recorded — asking for it first,
   *  in a sentence, the first time a voice is about to be made (UX-3). */
  const withConsent = (who: string | null, go: () => void) => {
    if (consentGiven.current) go()
    else setConsentAsk({ who, go })
  }

  const confirmConsent = async () => {
    if (!projectId || !consentAsk) return
    setConsenting(true)
    try {
      const r = await grantConsent(projectId)
      consentGiven.current = true
      setProject((p) => (p ? { ...p, consent: r.consent } : p))
      const { go } = consentAsk
      setConsentAsk(null)
      go()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not record that.')
    } finally {
      setConsenting(false)
    }
  }

  /** A line edited at the line (UX-1): Hear it says what was asked, in one
   *  sentence, to Voltage. Nothing is voiced outside a turn. */
  const hearLine = (_key: LineKey, request: LineRequest) => {
    const words = `“${request.text}”`
    const voice = request.voiceId ? voices.find((v) => v.voice_id === request.voiceId)?.name : undefined
    const how = `${request.delivery ? `, said ${request.delivery}` : ''}${voice ? `, in ${voice}'s voice` : ''}`
    const picture = request.mix === 'concatenate' ? 'holding the picture' : 'over the picture'
    const { start, end } = request.selection
    const line = (project?.statements ?? []).find((st) => st.start === start && st.end === end)
    // 20f: Edit it on a proposal voices that item again; on an added line, the new take swaps the old edit out.
    if (request.itemId) return takeTurn(`Voice ${request.itemId} again as ${words}${how}`)
    if (request.editId) {
      return takeTurn(`Redo the added line at ${clock(start)} (“${request.before ?? ''}”, ${request.editId}) as ${words}${how}: voice it at ${clock(start)}–${clock(end)}, ${picture}, ship it and take ${request.editId} out`)
    }
    if (request.mix === 'replace' && line) return takeTurn(`Replace the line at ${clock(start)} (“${line.text}”) with ${words}${how}`)
    if (request.at != null) return takeTurn(`Add ${words} at ${clock(request.at)}, ${picture}${how}`)
    if (!line || request.mix === 'layer') return takeTurn(`Add ${words} at ${clock(start)}–${clock(end)}, ${picture}${how}`)
    return takeTurn(`Add ${words} after the line at ${clock(start)}, ${picture}${how}`)
  }
  /** A take dragged to a new start: the same audio, placed again, stands under the line. */
  const moveTake = async (item: PlanItem, c: Candidate, start: number) => {
    if (!projectId) return
    setError(null)
    try {
      const moved = await moveCandidate(projectId, c.candidate_id, { start })
      setPlan((p) => (p ? { ...p, items: p.items.map((i) => (i.item_id === item.item_id ? { ...i, candidate: moved } : i)) } : p))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not move the take.')
    }
  }
  /** A kept line dragged to a new start: reverted and re-kept there, in one step. */
  const moveKept = async (editId: string, start: number) => {
    if (!projectId) return
    setError(null)
    try {
      const r = await moveEdit(projectId, editId, { start })
      const { selection: at, new_text: text, mix = 'replace' } = r.candidate.plan
      setApproved((a) => a.map((rev) => (
        rev.edit_id === editId ? { edit_id: r.edit_id, start: at.start, end: at.end, text, mix, partner: rev.partner ?? null }
        : rev.partner === editId ? { ...rev, partner: r.edit_id } : rev
      )))
      setDownload(null)
      if (await runExport()) setView('final')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not move the line.')
    }
  }

  /** Add it (20e): the proposal under a line goes into the video — its plan
   *  item is approved and rendered. A take that failed its sound check is
   *  added on the user's word. */
  const addItem = async (item: PlanItem) => {
    if (!projectId || !plan) return
    setError(null)
    try {
      const passed = item.candidate?.continuity.passed ?? true
      takeInApproval(await approvePlan(projectId, plan.plan_id, passed ? { items: [item.item_id] } : { items: [item.item_id], override: true }))
      setPreview(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not add that line.')
    } finally {
      void refreshUsage(projectId)
    }
  }
  /** Discard a proposal: it leaves the plan; nothing in the video changes. */
  const discardItem = async (item: PlanItem) => {
    if (!projectId || !plan) return
    setError(null)
    try {
      setPlan(await dismissItem(projectId, plan.plan_id, item.item_id))
      setPreview(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not discard that line.')
    }
  }
  const removeStatement = async (s: Statement) => {
    if (!projectId) return
    setError(null)
    try {
      const r = await removeLine(projectId, { start: s.start, end: s.end })
      setPlan(r.plan)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not propose removing that line.')
    }
  }
  /** Move a line of the original speech to another time (UX-1c): two paired
   *  edits — room tone where it was, the words over the picture from `to`. */
  const shiftStatement = async (s: Statement, to: number) => {
    if (!projectId) return
    setError(null)
    setPlacing(null)
    try {
      const r = await shiftLine(projectId, { start: s.start, end: s.end, to })
      setApproved((a) => [...a,
        { edit_id: r.removed_edit_id, start: r.from.start, end: r.from.end, text: '', mix: 'remove', partner: r.edit_id },
        { edit_id: r.edit_id, start: r.selection.start, end: r.selection.end, text: s.text, mix: 'layer', partner: r.removed_edit_id },
      ])
      setDownload(null)
      if (await runExport()) setView('final')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not move that line.')
    }
  }
  /** Play a take in place: the video runs from the line while the take's
   *  audio plays over it (the original muted for a replacement). Over the
   *  final render when there is one and its clock is the source's (20e), so
   *  the lines already added are heard under it; else over the original. */
  const playTake = (c: Candidate) => {
    if (!project) return
    const audio = takeAudio.current ?? (takeAudio.current = new Audio())
    if (playingTake === c.candidate_id) {
      audio.pause()
      setPlayingTake(null)
      playingCandidate.current = null
      return
    }
    audio.src = artifactUrl(project.project_id, c.audio.sha256)
    audio.onended = () => { setPlayingTake(null); playingCandidate.current = null }
    playingCandidate.current = c
    const span = c.plan.selection
    const overFinal = rendered !== null && pieces.every((p) => p.kind === 'copy')
    setView(overFinal ? 'final' : 'original')
    setSeekRequest((r) => ({ time: span.start, id: (r?.id ?? 0) + 1, play: true, until: span.start + c.audio.duration + 0.3 }))
    setCurrentTime(span.start)
    setPlayingTake(c.candidate_id)
    const started = audio.play() as Promise<void> | undefined
    if (started && typeof started.catch === 'function') started.catch(() => {})
  }

  const rememberAutonomy = async (value: Autonomy) => {
    if (!projectId || value === autonomy) return
    setAutonomy(value)
    setMayDo((m) => ({ ...m, autonomy: value }))
    try {
      await updateSettings(projectId, { autonomy: value })
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't save that setting. Try it again.")
    }
  }

  /** "What Voltage may do" (20d): each choice in the sheet is saved as it is made. */
  const changeMayDo = async (change: Partial<Pick<MayDo, 'autonomy' | 'turn_usd' | 'effort'>>) => {
    if (!projectId) return
    if (change.autonomy) return rememberAutonomy(change.autonomy)
    setMayDo((m) => ({ ...m, ...change }))
    try {
      const saved = await updateSettings(projectId, change)
      setMayDo((m) => ({ ...m, turn_usd: saved.turn_usd ?? m.turn_usd, effort: saved.effort ?? m.effort, ceiling_usd: saved.ceiling_usd ?? m.ceiling_usd }))
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't save that setting. Try it again.")
    }
  }

  /** UX-5: the place Voltage guessed, confirmed or corrected; the plan uses it by name. */
  const confirmThePlace = async (place: string) => {
    if (!projectId) return
    try {
      const sight = await confirmPlace(projectId, place)
      setReading((r) => (r ? { ...r, sight } : r))
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't keep that place. Try again.")
    }
  }

  /** A goal for the whole video, an answer to Voltage's question, or a change
   *  to the plan: every one is a turn (20c; the form planner is gone). */
  const clarify = (answer?: string) => {
    if (!plan?.question) return
    return takeTurn(answer ?? plan.question.guess ?? plan.question.options[0])
  }

  /** The box is for the whole video: a goal, a change to the plan, an answer.
   *  With words selected on the Precise timeline, the sentence names the time. */
  const submitComposer = (text: string) => void takeTurn(selection ? `At ${clock(selection.start)}: ${text}` : text)

  /** Phase 20: one turn of Voltage with tools. The steps arrive as messages
   *  while it works; the result is the plan and Voltage's closing line. A
   *  paid step needs the project's consent (UX-3): asked before the turn
   *  under Just do it, and when the server asks for it (403) under Check
   *  with me — then the same turn goes again, once. */
  const takeTurn = async (text: string, again = false) => {
    if (!projectId) return
    if (autonomy === 'draft' && !consentGiven.current) return withConsent(null, () => void takeTurn(text, again))
    if (!again) say({ role: 'user', text })
    setError(null)
    setTurnBusy(true)
    setTurnStep('Thinking…')
    try {
      const job = await postTurn(projectId, text)
      await followTurn(job.job_id)
    } catch (e) {
      setTurnBusy(false)
      setTurnStep(null)
      if (e instanceof ApiError && e.status === 403 && !consentGiven.current && !again) {
        return withConsent(null, () => void takeTurn(text, true))
      }
      tell(e instanceof ApiError ? e.message : "I couldn't take that in. Try saying it another way.")
    }
  }

  // One pull at a time, and nothing appended twice: a step's seq is claimed before it is shown.
  const pulling = useRef<Promise<void> | null>(null)
  const pullMessages = () => {
    if (!projectId) return Promise.resolve()
    if (pulling.current) return pulling.current
    pulling.current = (async () => {
      try {
        const fresh = await getMessages(projectId, seenSeq.current)
        for (const m of fresh) {
          if ((m.seq ?? 0) <= seenSeq.current) continue
          seenSeq.current = m.seq ?? seenSeq.current
          if (m.role === 'assistant') say(m)
        }
      } catch {
        // the next tick pulls again
      } finally {
        pulling.current = null
      }
    })()
    return pulling.current
  }

  const followTurn = async (jobId: string) => {
    if (!projectId) return
    try {
      const finished = await pollJob(jobId, {
        onUpdate: (j) => { setTurnStep(j.step || 'Working…'); void pullMessages() },
      })
      await pullMessages()
      if (finished.status === 'failed') tell(finished.error ?? "Something went wrong on my side. Say it again and I'll retry.")
      const result = finished.result as { type?: string; plan?: Plan } | null
      let fresh: Plan | null = null
      if (result && result.type === 'turn' && result.plan) fresh = result.plan
      else {
        const latest = await getProject(projectId).catch(() => null)
        if (latest?.plan) fresh = latest.plan
      }
      if (fresh) {
        setPlan(fresh)
        await takeInShipped(fresh)
      }
    } catch (e) {
      if (!(e instanceof PollCancelled)) tell('I lost track of that turn. Say it again.')
    } finally {
      setTurnBusy(false)
      setTurnStep(null)
      void refreshUsage(projectId)
      // A turn may have made a voice (designed, or from the library): the catalogue is read again.
      listVoices().then(takeInVoices).catch(() => {})
    }
  }

  /** 15e/20c: the voice picked by hand on the plan card is asked of Voltage in words. */
  const pickPlanVoice = (voiceIdPicked: string) => {
    const name = voices.find((v) => v.voice_id === voiceIdPicked)?.name ?? voiceIdPicked
    return takeTurn(`Use ${name}'s voice for the lines`)
  }

  /** Another take of a line, or a failed one again: asked of Voltage in words (20c). */
  const redoTheItem = (item: PlanItem) => takeTurn(`Another take of “${item.new_text}” (${item.item_id})`)

  /** An approved edit as the transcript shows it (20g: with its level). */
  const asRevision = (e: ApprovedEditSummary): Revision => ({
    edit_id: e.edit_id, start: e.selection.start, end: e.selection.end, text: e.new_text, mix: e.mix, partner: e.partner ?? null, level_db: e.level_db ?? null,
  })
  /** The plan item just approved, as a revision. */
  const itemRevision = (i: PlanItem): Revision => ({
    edit_id: i.edit_id!, start: i.candidate?.plan.selection.start ?? i.selection.start,
    end: i.candidate?.plan.selection.end ?? i.selection.end, text: i.new_text, mix: i.mix, level_db: i.candidate?.plan.level_db ?? null,
  })

  /** 20g: after a turn, the edits as the server has them — Voltage may have undone or releveled a line — so the transcript never shows a stale row. */
  const syncEdits = async (): Promise<{ changed: boolean; render: { download: { url: string; filename: string }; duration: number } | null }> => {
    if (!projectId) return { changed: false, render: null }
    const latest = await getProject(projectId).catch(() => null)
    if (!latest) return { changed: false, render: null }
    const live = latest.edits.filter((e) => !e.reverted).map(asRevision)
    const before = approved.map((r) => r.edit_id).sort().join(',')
    const after = live.map((r) => r.edit_id).sort().join(',')
    setApproved(live)
    if (before === after) return { changed: false, render: null }
    setPreview(null)
    if (live.length === 0) { setRendered(null); setDownload(null); setSegments([]); setInserts([]); setPieces([]); setView('original'); return { changed: true, render: null } }
    const render = await runExport()
    if (render) setView('final')
    return { changed: true, render }
  }

  /** 20g: a line mixed under the words or at full level, nothing voiced again. */
  const changeLevel = async (target: { editId?: string; candidate?: Candidate; item?: PlanItem }, levelDb: number) => {
    if (!projectId) return
    setError(null)
    try {
      if (target.editId) {
        const r = await setEditLevel(projectId, target.editId, levelDb)
        setApproved((all) => all.map((rev) => (rev.edit_id === target.editId ? { ...rev, edit_id: r.edit_id, level_db: r.candidate.plan.level_db ?? null } : rev)))
        setPreview(null)
        if (await runExport()) setView('final')
      } else if (target.candidate && target.item) {
        const c = await setCandidateLevel(projectId, target.candidate.candidate_id, levelDb)
        const id = target.item.item_id
        setPlan((p) => (p ? { ...p, items: p.items.map((i) => (i.item_id === id ? { ...i, candidate: c } : i)) } : p))
        setPreview(null)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not change the level.')
    }
  }

  /** The plan after an approval: its items as they stand, the new edits as
   *  revisions on their lines, and the render, which the player switches to.
   *  Returns the download when there is a render. */
  const takeInApproval = (result: PlanApproval) => {
    setPlan(result.plan)
    setPreview(null)
    const fresh = result.plan.items.filter((i) => i.status === 'approved' && i.edit_id
      && !approved.some((r) => r.edit_id === i.edit_id))
    setApproved((a) => [...a, ...fresh.map(itemRevision)])
    if (!result.export || !projectId) return null
    setSegments(result.export.segments)
    setInserts(result.export.inserts ?? [])
    setPieces(result.export.pieces ?? piecesFromInserts(result.export.inserts ?? [], project?.duration ?? 0))
    const stem = (project?.filename ?? 'video').replace(/\.[^.]+$/, '')
    const url = artifactUrl(projectId, result.export.render.sha256)
    const download = { url, filename: `${stem}-edited.mp4` }
    setDownload(download)
    setRendered({ url, duration: result.export.render.duration })
    setView('final')
    return download
  }

  /** Under Just do it, Voltage ships inside its turn. The lines it shipped
   *  come back as approved items the panel has not seen: they become
   *  revisions, the edited video is rendered (no paid step), the player
   *  switches to it and the sheet says what is in the file — the same as a
   *  hand-shipped approval. */
  const takeInShipped = async (fresh: Plan) => {
    if (!projectId) return
    const went = fresh.items.filter((i) => i.status === 'approved' && i.edit_id
      && !approved.some((r) => r.edit_id === i.edit_id))
    const { changed, render } = await syncEdits()
    if (went.length === 0 || !changed || !render) return
    setShipped({
      items: went,
      held: fresh.items.filter((i) => i.status === 'ready').length,
      removed: approved.filter((r) => r.mix === 'remove').length,
      before: project?.duration ?? 0,
      after: render.duration,
      download: render.download,
      spendUsd: fresh.spend_usd,
      takesVoiced: fresh.takes_voiced ?? 0,
    })
  }

  /** Add them all (20e): every proposal goes into the video in one render,
   *  flagged takes included — the user asked for all of them. */
  const approveAll = async (items: PlanItem[]) => {
    if (!projectId || !plan) return
    setError(null)
    try {
      const result = await approvePlan(projectId, plan.plan_id, {
        items: items.map((i) => i.item_id), override: items.some((i) => !(i.candidate?.continuity.passed ?? true)),
      })
      takeInApproval(result)
      setPreview(null)
      if (result.skipped.length > 0) {
        setError(`${result.skipped.length} ${result.skipped.length === 1 ? 'line was' : 'lines were'} not added. Hear them, then Add it one by one or ask for another take.`)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not add those lines.')
    } finally {
      void refreshUsage(projectId)
    }
  }

  /** A variant: this clip again, as a new project, with the plan as a draft. */
  const makeVariant = async () => {
    if (!projectId) return
    setVarianting(true)
    setError(null)
    try {
      const made = await createVariant(projectId)
      window.location.hash = made.project_id
      await openProject(made.project_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not make a variant.')
    } finally {
      setVarianting(false)
    }
  }

  const findSpeakers = async () => {
    if (!projectId) return
    setDetecting(true)
    setError(null)
    try {
      const updated = await detectSpeakers(projectId)
      setProject((p) => (p ? { ...p, statements: updated.statements, speakers: updated.speakers } : p))
      setTranscript(updated.transcript)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not detect speakers.')
    } finally {
      setDetecting(false)
      void refreshUsage(projectId)
    }
  }

  const changeSpeaker = async (
    label: string, change: { name?: string; voice_id?: string; clear_voice?: boolean },
  ) => {
    if (!projectId) return
    try {
      const speakers = await updateSpeaker(projectId, label, change)
      setProject((p) => (p ? { ...p, speakers } : p))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not update that speaker.')
    }
  }

  const seekToStatement = (s: Statement) => {
    setSelection({ start: s.start, end: s.end })
    const edited = view === 'final' && rendered !== null
    const time = edited ? renderTimeFrom(s.start, pieces) : s.start
    setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 }))
    setCurrentTime(time)
  }

  /** Undo an approved edit: the transcript shows the line as shot, and the
   *  render no longer includes it. */
  const revert = async (editId: string) => {
    if (!projectId) return
    setError(null)
    try {
      await revertEdit(projectId, editId)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not revert that edit.')
      return
    }
    const gone = approved.find((r) => r.edit_id === editId)
    const remaining = approved.filter((r) => r.edit_id !== editId && r.edit_id !== gone?.partner)
    setApproved(remaining)
    setDownload(null)
    if (plan?.items.some((i) => i.edit_id === editId)) {
      getPlan(projectId, plan.plan_id).then(setPlan).catch(() => {})
    }
    if (remaining.length > 0) {
      if (await runExport()) setView('final')
    } else {
      setRendered(null)
      setSegments([])
      setInserts([])
      setPieces([])
      setView('original')
    }
    setPreview(null)
  }

  /** 20e: the preview render with the proposals mixed in, for "With proposals"
   *  playback; made once per set of takes and dropped when they change. */
  const ensurePreview = async () => {
    if (!projectId || previewing) return
    const key = (plan?.items ?? []).filter((i) => i.kind === 'planned' && i.status === 'ready').map((i) => i.candidate?.candidate_id ?? i.item_id).join(',')
    if (preview && preview.key === key) return
    setPreviewing(true)
    setError(null)
    try {
      const manifest = await exportProject(projectId, true)
      const url = artifactUrl(projectId, manifest.render.sha256)
      setPreview({ url, duration: manifest.render.duration, key,
        pieces: manifest.pieces ?? piecesFromInserts(manifest.inserts ?? [], project?.duration ?? 0) })
    } catch {
      setError('Could not render the preview with the proposals.')
      setView(rendered ? 'final' : 'original')
    } finally {
      setPreviewing(false)
    }
  }

  /** Renders the approved edits; the render (and its download) once it is ready to play, else null. */
  const runExport = async (
    id: string | null = projectId, filename = project?.filename,
  ): Promise<{ download: { url: string; filename: string }; duration: number } | null> => {
    if (!id) return null
    setError(null)
    setExporting(true)
    try {
      const manifest = await exportProject(id)
      setSegments(manifest.segments)
      setInserts(manifest.inserts ?? [])
      setPieces(manifest.pieces ?? piecesFromInserts(manifest.inserts ?? [], project?.duration ?? 0))
      const stem = (filename ?? 'video').replace(/\.[^.]+$/, '')
      const url = artifactUrl(id, manifest.render.sha256)
      const download = { url, filename: `${stem}-edited.mp4` }
      setDownload(download)
      setRendered({ url, duration: manifest.render.duration })
      return { download, duration: manifest.render.duration }
    } catch {
      setError('Export failed.')
      return null
    } finally {
      setExporting(false)
    }
  }

  const openProject = async (id: string) => {
    clearEditor()
    setLoading(true)
    try {
      const opened = await getProject(id)
      const live = opened.edits.filter((e) => !e.reverted)
      takeIn(opened, live.length > 0 || opened.messages.length > 0)
      setMessages(opened.messages)
      seenSeq.current = Math.max(0, ...opened.messages.map((m) => m.seq ?? 0))
      setApproved(live.map(asRevision))
      // Approved edits are rendered again, so Play hears them straight away.
      if (live.length > 0 && await runExport(opened.project_id, opened.filename)) {
        setView('final')
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not open that project.')
    } finally {
      setLoading(false)
    }
  }

  const removeProject = async (id: string) => {
    try {
      await deleteProject(id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not delete that project.')
    }
    await refreshProjects()
  }

  if (me === null) {
    return (
      <div className="flex min-h-dvh items-center justify-center gap-3 bg-background text-muted-foreground" role="status" aria-busy="true">
        <Presence size={20} working />
        <span>Opening…</span>
      </div>
    )
  }
  if (me.mode === 'google' && (!me.user || signedOut)) {
    return <SignIn error={signedOut ? 'Your session ended. Sign in again to continue.' : null} />
  }
  if (stage === 'load' || !project) {
    return (
      <LoadScreen
        onLoad={load}
        onLoadSample={loadSample}
        loading={loading}
        progress={uploadShare}
        error={error}
        who={me.user ? { name: me.user.name ?? me.user.email ?? 'You', picture: me.user.picture } : null}
        onSignOut={me.user ? () => void signOut() : undefined}
      >
        <ProjectList projects={projects} onOpen={(id) => void openProject(id)} onDelete={(id) => void removeProject(id)} />
      </LoadScreen>
    )
  }
  const speakers = project.speakers ?? []
  // 20f: the spoken lines only; added lines and proposals are rows of their own in LineDoc.
  const statements: Statement[] = project.statements ?? []
  const leave = () => {
    clearEditor()
    window.location.hash = ''
    setStage('load')
  }

  // Where things stand line by line: the plan's items, and nothing else.
  const planItems = plan?.items.filter((i) => i.kind === 'planned' && i.enabled) ?? []
  const pendingLines: PendingLine[] = planItems
    .filter((i) => ['planned', 'working', 'ready', 'needs-you', 'failed'].includes(i.status))
    .map((i) => ({ selection: i.selection, status: i.status, text: i.new_text, mix: i.mix }))
  const readyItems = plan?.items.filter((i) => i.kind === 'planned' && i.status === 'ready') ?? []
  // 20e: which render plays. "With proposals" is a preview render keyed by the takes it carries.
  const previewKey = readyItems.map((i) => i.candidate?.candidate_id ?? i.item_id).join(',')
  const previewReady = preview !== null && preview.key === previewKey
  const shown = view === 'final' && rendered ? { url: rendered.url, duration: rendered.duration, pieces }
    : view === 'proposals' && previewReady ? { url: preview!.url, duration: preview!.duration, pieces: preview!.pieces }
    : null
  const busy = turnBusy
  const clarifying = plan?.status === 'clarifying'
  const stateWord = clarifying ? 'has a question'
    : turnBusy ? 'working'
    : editingLine ? 'standing by'
    : plan?.status === 'proposed' ? 'has a plan'
    : readyItems.length > 0 ? 'has proposals'
    : 'ready'
  const sendLabel = clarifying ? 'Answer' : 'Send'
  const placeholder = clarifying ? 'Answer, or tell Voltage anything else'
    : selection ? 'Ask for a change, e.g. say "30% off" instead'
    : plan ? 'Say what to change, or ask for another take; "ship it" when it sounds right'
    : 'What should this video say?'

  const sourceClock = shown ? sourceTimeFrom(currentTime, shown.pieces) : currentTime
  const voiceLine = usage?.lines.find((l) => l.vendor === 'elevenlabs' && l.units > 0)
  const usdPerChar = voiceLine ? voiceLine.usd / voiceLine.units : null
  const playingMix = playingTake
    ? (playingCandidate.current?.candidate_id === playingTake ? playingCandidate.current.plan.mix : null)
      ?? plan?.items.find((i) => i.candidate?.candidate_id === playingTake)?.candidate?.plan.mix ?? 'replace'
    : null
  // What is waiting on you, line by line, for the rail's badge.
  const needsYou = planItems.filter((i) => i.status === 'needs-you')
  // UX-7b: the monitor's timeline and caption. Times follow the version that
  // plays: an insert in the edited render pushes everything after it later.
  const toRender = (t: number) => (shown ? renderTimeFrom(t, shown.pieces) : t)
  const blocks: Block[] = [
    ...statements.map((s) => ({ start: toRender(s.start), end: toRender(s.end), tone: speakerSlot(speakers, s.speaker) as Block['tone'] })),
    ...approved.filter((r) => r.mix !== 'remove').map((r) => ({ start: toRender(r.start), end: toRender(r.end), tone: 'changed' as const })),
    ...pendingLines.filter((l) => l.text).map((l) => ({ start: toRender(l.selection.start), end: toRender(l.selection.end), tone: 'changed' as const })),
  ]
  // A take in hand, not yet kept, is captioned with its words too: the picture
  // shows what you are about to hear.
  const takesInHand: CaptionPending[] = readyItems.flatMap((i) => (
    i.candidate ? [{ selection: i.candidate.plan.selection, text: i.candidate.plan.new_text, mix: i.candidate.plan.mix }] : []
  ))
  const captionRuns = captionAt(sourceClock, statements, approved, [...pendingLines, ...takesInHand], transcript, rendered !== null && view === 'original')
  // A take playing in place with word times (the polish pass): its words, lit as they are said.
  const spoken = playingTake && playingCandidate.current?.candidate_id === playingTake && playingCandidate.current.words?.length
    ? takeCaption(playingCandidate.current.words, currentTime - playingCandidate.current.plan.selection.start)
    : null
  const caption = spoken
    ? spoken.map((w, k) => <Fragment key={k}>{k > 0 && ' '}<ins data-said={w.said || undefined}>{w.text}</ins></Fragment>)
    : captionRuns?.map((r, k) => <Fragment key={k}>{k > 0 && ' '}{r.kind === 'ins' ? <ins>{r.text}</ins> : r.text}</Fragment>)

  return (
    <div
      className="flex h-dvh flex-col bg-background max-[960px]:h-auto max-[960px]:min-h-dvh"
      data-panel={panelHidden ? 'hidden' : undefined}
    >
      <a className="skip" href="#main">Skip to the transcript</a>
      {/* UX-9: the studio's header — brand, the file, the play switch, the autonomy, the money, the exports. */}
      <header className="relative z-10 flex min-h-13 items-center gap-2.5 border-b bg-card px-3 max-[960px]:flex-wrap max-[960px]:gap-y-2 max-[960px]:py-2">
        <h1 className="m-0 flex items-center gap-2 text-sm font-semibold tracking-tight"><Presence size={16} />Voltage</h1>
        <span className="flex min-w-0 items-center gap-2 rounded-md border bg-muted px-2 py-1 font-mono text-xs text-muted-foreground max-[960px]:max-w-[50vw]">
          <Film className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0 truncate font-medium text-foreground" title={project.filename}>{project.filename}</span>
          <span className="tnum whitespace-nowrap">{project.duration.toFixed(1)} s{speakers.length > 0 ? ` · ${speakers.length} ${speakers.length === 1 ? 'speaker' : 'speakers'}` : ''}</span>
        </span>
        <span className="flex-1" />
        {(rendered || readyItems.length > 0) && (
          <div className="inline-flex gap-0.5 rounded-md border bg-muted p-0.5" role="group" aria-label="Play">
            {([
              ...(rendered ? [['final', 'Final'] as const] : []),
              ...(readyItems.length > 0 ? [['proposals', 'With proposals'] as const] : []),
              ['original', 'Original'] as const,
            ]).map(([v, label]) => (
              <Button
                key={v}
                variant="ghost"
                size="sm"
                className={cn('h-7 whitespace-nowrap px-2.5 text-xs', view === v ? 'bg-background text-foreground shadow-xs hover:bg-background' : 'text-muted-foreground')}
                aria-pressed={view === v}
                onClick={() => { setView(v); setCurrentTime(0); if (v === 'proposals') void ensurePreview() }}
              >
                {v === 'proposals' && <span className={cn('size-1.5 rounded-full bg-primary', !previewReady && previewing && 'animate-pulse')} aria-hidden="true" />}
                {label}
              </Button>
            ))}
          </div>
        )}
        <AutonomySwitch value={autonomy} onChange={(v) => void rememberAutonomy(v)} />
        <span className="flex-1" />
        <SpendMeter usage={usage} />
        <ExportBar segments={segments} inserts={inserts} pieces={pieces} onExport={() => void runExport()} download={download} busy={exporting} onVariant={() => void makeVariant()} varianting={varianting} />
        <Button variant="ghost" size="icon" onClick={() => setMayDoOpen(true)} aria-label="What Voltage may do: the autonomy, the turn's spend cap and the effort" title="What Voltage may do">
          <SlidersHorizontal aria-hidden="true" />
        </Button>
        <WhatVoltageMayDo open={mayDoOpen} value={mayDo} onChange={(c) => void changeMayDo(c)} onClose={() => setMayDoOpen(false)} />
        <ThemeToggle />
        {me.user && (
          <span className="flex items-center gap-2 border-l pl-2 text-sm">
            {me.user.picture ? <img className="size-6 rounded-full" src={me.user.picture} alt="" referrerPolicy="no-referrer" /> : null}
            <span className="max-w-36 truncate max-[960px]:hidden">{me.user.name ?? me.user.email ?? 'You'}</span>
            <Button variant="ghost" size="sm" onClick={() => void signOut()}>Sign out</Button>
          </span>
        )}
      </header>

      <div className="flex min-h-0 flex-1 gap-2 p-2 max-[960px]:flex-col">
        {/* The dock: real destinations only. */}
        <nav className="flex w-10 shrink-0 flex-col items-center gap-1 rounded-lg border bg-card py-2 max-[960px]:w-auto max-[960px]:flex-row max-[960px]:px-2" aria-label="Dock">
          <Button variant="ghost" size="icon" onClick={leave} aria-label="Projects" title="Projects"><FolderOpen aria-hidden="true" /></Button>
          <Button variant="ghost" size="icon" className="bg-accent text-primary" aria-label="Workspace" aria-current="page" title="Workspace"><AudioLines aria-hidden="true" /></Button>
          <Button variant="ghost" size="icon" onClick={() => document.getElementById('speakers')?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })} aria-label="Speakers" title="Speakers"><Users aria-hidden="true" /></Button>
          <Button variant="ghost" size="icon" onClick={() => setVoicesOpen(true)} aria-label="Your voices" title="Your voices"><Mic aria-hidden="true" /></Button>
          <span className="flex-1" />
          <Button variant="ghost" size="icon" onClick={() => setPanelHidden((h) => !h)} aria-label={panelHidden ? 'Bring Voltage back' : 'Tuck Voltage away'} title={panelHidden ? 'Bring Voltage back' : 'Tuck Voltage away'}><Zap aria-hidden="true" className={cn(panelHidden ? 'text-muted-foreground' : 'text-primary')} /></Button>
        </nav>

        {/* The player and its lanes. */}
        <main id="main" className="flex min-h-0 flex-[41_1_0%] flex-col gap-2 overflow-y-auto rounded-lg border bg-card p-2.5 max-[960px]:flex-none max-[960px]:overflow-visible" aria-busy={turnBusy || undefined}>
          <Player
            src={shown ? shown.url : artifactUrl(project.project_id, project.media.sha256)}
            duration={shown ? shown.duration : project.duration}
            currentTime={currentTime}
            onSeek={setCurrentTime}
            onTimeUpdate={setCurrentTime}
            seekRequest={seekRequest}
            blocks={blocks}
            words={transcript}
            caption={caption}
            muted={playingTake !== null && playingMix === 'replace'}
          >
            <Button variant={precise ? 'secondary' : 'ghost'} size="sm" aria-pressed={precise} onClick={() => setPrecise((p) => !p)}>Precise</Button>
            <span className="flex-1" />
            <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground" role="status" aria-busy={previewing || undefined} data-testid="retime">
              {view === 'proposals' && !previewReady ? (
                <><Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden="true" />{previewing ? 'Rendering with the proposals…' : 'The proposals changed; rendering again…'}</>
              ) : view === 'proposals' ? `Preview mix with ${readyItems.length} proposed ${readyItems.length === 1 ? 'take' : 'takes'}`
              : view === 'final' && rendered ? 'The final'
              : 'The original'}
              {shown && shown.pieces.some((p) => p.kind === 'flex' && p.factor != null && Math.abs(p.factor - 1) > 0.005) && (
                <span className="text-ok">· picture flexed</span>
              )}
            </span>
          </Player>
          <Lanes
            duration={project.duration}
            currentTime={sourceClock}
            statements={statements}
            speakers={speakers}
            revisions={approved}
            items={planItems}
            pieces={shown?.pieces ?? pieces}
            onSeek={(t) => { const time = shown ? renderTimeFrom(t, shown.pieces) : t; setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 })); setCurrentTime(time) }}
            placing={placing}
            onPlace={(start) => setPlacing((p) => (p ? { ...p, start } : p))}
          />
          {error && <div className="rounded-md border border-needs/40 bg-needs-soft px-3 py-2 text-sm text-needs" role="alert">{error}</div>}
          {precise && (
            <Timeline
              key={project.project_id}
              words={transcript}
              duration={project.duration}
              selection={selection}
              currentTime={sourceClock}
              onSelect={setSelection}
            />
          )}
          <div id="speakers">
            <SpeakersBar
              speakers={speakers}
              voices={voices}
              hasSpeech={transcript.length > 0}
              detecting={detecting}
              onDetect={() => void findSpeakers()}
              onRename={(label, name) => void changeSpeaker(label, { name })}
              onVoice={(label, id) => void changeSpeaker(label, id ? { voice_id: id } : { clear_voice: true })}
            />
          </div>
        </main>

        {/* The transcript and takes. */}
        <section className="flex min-h-0 flex-[35_1_0%] flex-col overflow-y-auto rounded-lg border bg-card max-[960px]:flex-none max-[960px]:overflow-visible" aria-label="Transcript and takes">
          <LineDoc
            statements={statements}
            words={transcript}
            speakers={speakers}
            voices={voices}
            revisions={approved}
            selection={selection}
            currentTime={sourceClock}
            pendingLines={pendingLines}
            items={planItems}
            disabled={turnBusy}
            usdPerChar={usdPerChar}
            playing={playingTake}
            onSeek={seekToStatement}
            onHear={hearLine}
            onAdd={(item) => addItem(item)}
            onDiscard={(item) => discardItem(item)}
            onAddAll={(items) => approveAll(items)}
            onHearTake={(_item, c) => playTake(c)}
            onLevel={(target, levelDb) => void changeLevel(target, levelDb)}
            backgroundDb={BACKGROUND_DB}
            onDelivery={(item, delivery) => void takeTurn(`Voice ${item.item_id} again, said ${delivery}`)}
            onUndo={(id) => void revert(id)}
            onRemove={(s) => void removeStatement(s)}
            onShift={(s, to) => void shiftStatement(s, to)}
            onMove={(item, c, start) => void moveTake(item, c, start)}
            onMoveKept={(id, start) => void moveKept(id, start)}
            placing={placing}
            onPlacing={setPlacing}
            onEditingChange={setEditingLine}
            duration={project.duration}
          />
        </section>

        {/* Voltage. */}
        {panelHidden ? (
          <aside className="flex min-h-0 w-14 shrink-0 flex-col items-center gap-3.5 rounded-lg border bg-card py-3.5 max-[960px]:sticky max-[960px]:bottom-0 max-[960px]:z-10 max-[960px]:w-auto max-[960px]:flex-row max-[960px]:gap-2.5 max-[960px]:px-4 max-[960px]:py-2" aria-label="Voltage, tucked away" data-testid="rail">
            <Button variant="ghost" size="icon" onClick={showPanel} aria-label={`Show Voltage. ${stateWord[0].toUpperCase()}${stateWord.slice(1)}`}>
              <Presence size={18} working={busy} />
            </Button>
            {(needsYou.length > 0 || readyItems.length > 0) && (
              <span
                className={cn('flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 font-mono text-xs font-semibold text-background', needsYou.length > 0 ? 'bg-needs' : 'bg-changed')}
                aria-hidden="true"
              >{needsYou.length > 0 ? needsYou.length : readyItems.length}</span>
            )}
            <span className="rotate-180 whitespace-nowrap text-sm leading-none text-muted-foreground [writing-mode:vertical-rl] max-[960px]:hidden" aria-hidden="true">{stateWord}</span>
            <span className="flex-1 max-[960px]:hidden" />
            {/* On a phone the strip carries the composer too (the polish pass): sending brings Voltage back so the reply is seen. */}
            <form
              className="hidden min-w-0 flex-1 items-center gap-1.5 rounded-lg border bg-background py-1 pr-1 pl-3 focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 max-[960px]:flex"
              onSubmit={(e) => {
                e.preventDefault()
                const text = railText.trim()
                if (!text) return
                setRailText('')
                showPanel()
                submitComposer(text)
              }}
            >
              <input
                className="min-h-9 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground pointer-coarse:min-h-11"
                type="text"
                aria-label="Ask Voltage"
                placeholder={placeholder}
                value={railText}
                onChange={(e) => setRailText(e.target.value)}
              />
              <Button type="submit" size="icon" className="rounded-full" aria-label={sendLabel} title={sendLabel} disabled={railText.trim() === ''}>
                <ArrowUp aria-hidden="true" />
              </Button>
            </form>
            <Button variant="outline" size="sm" className="hidden max-[960px]:inline-flex" onClick={showPanel}>Open</Button>
            <Button variant="ghost" size="icon" className="max-[960px]:hidden" onClick={showPanel} aria-label="Show Voltage">
              <ChevronLeft aria-hidden="true" />
            </Button>
          </aside>
        ) : (
        <aside ref={panelRef} className="flex min-h-0 flex-[24_1_0%] flex-col rounded-lg border bg-card max-[960px]:min-h-[60dvh] max-[960px]:flex-none" aria-label="Voltage" aria-busy={busy || undefined}>
          <ChatPanel
            messages={messages}
            projectId={projectId ?? undefined}
            canSubmit
            onSubmit={submitComposer}
            inputRef={composerRef}
            seed={seed}
            placeholder={placeholder}
            sendLabel={sendLabel}
            cap={`Turn cap $${mayDo.turn_usd.toFixed(2)}`}
            hint={clarifying ? 'Pick an answer above, or just say "go" and Voltage will use its guess.'
              : selection && precise ? `Talking about the words at ${clock(selection.start)}.`
              : (project.statements?.length ?? 0) === 0 ? 'For the whole video: what it should say, a brief, or ask me to look at it and help.'
              : 'For the whole video: a goal, or a change to the plan. To change one line, click it.'}
            header={
              <div className="flex flex-none items-center gap-2.5 border-b px-3.5 py-2.5">
                <Presence size={16} working={busy} />
                <div className="flex min-w-0 flex-col">
                  <h2 className="m-0 text-sm font-semibold tracking-tight">Voltage</h2>
                  <span className="font-mono text-xs text-muted-foreground" role="status">{stateWord} · {autonomy === 'ask' ? 'Check with me' : 'Just do it'}</span>
                </div>
                <span className="flex-1" />
                <Button variant="ghost" size="sm" onClick={() => setPanelHidden(true)} aria-label="Hide Voltage. Press backslash to show it again">
                  Hide <kbd className="pointer-events-none inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 font-mono text-xs text-muted-foreground" aria-hidden="true">\</kbd>
                  <ChevronRight aria-hidden="true" />
                </Button>
              </div>
            }
          >
            {!plan && messages.length === 0 && (
              <ReadingCard
                project={project}
                reading={readingBusy ? null : (reading ?? undefined)}
                speakers={speakers}
                onName={(label, name) => void changeSpeaker(label, { name })}
                onPlace={(place) => void confirmThePlace(place)}
                onExample={(text) => setSeed({ text, id: Date.now() })}
              />
            )}
            {clarifying && plan?.question && (
              <div className="flex flex-col gap-2.5 rounded-lg border border-primary/50 bg-card p-3.5 shadow-sm" data-testid="clarify">
                <div className="flex items-center gap-1.5 font-mono text-xs uppercase tracking-wide text-muted-foreground">
                  <ShieldCheck className="size-3.5 text-ok" aria-hidden="true" />{plan.question.gate ? 'Your go is needed' : 'One question'}
                </div>
                <div className="text-chat"><strong>{plan.question.text}</strong></div>
                <div className="flex flex-wrap gap-1.5">
                  {plan.question.options.map((o) => (
                    <Button key={o} variant={o === plan.question?.guess ? 'default' : 'outline'} size="sm" onClick={() => void clarify(o)}>{o}</Button>
                  ))}
                </div>
                <div className="text-sm leading-normal text-muted-foreground" role="status">
                  {plan.question.gate ? 'Say go, or pick one.' : `${plan.question.guess ? `My guess is ${plan.question.guess}. ` : ''}Pick one, or answer in your own words.`}
                </div>
              </div>
            )}
            {editingLine && !turnBusy && (
              <div className="text-base leading-relaxed text-muted-foreground">
                You're on {clock(editingLine.start)}. I'll stay out of the way while you write; Voice it brings the line to me.
              </div>
            )}
            {plan && editingLine && plan.status === 'done' && !showPlanWhileEditing && (
              <Button variant="outline" className="h-auto justify-start py-2.5 text-left font-normal text-muted-foreground" onClick={() => setShowPlanWhileEditing(true)}>
                Earlier: {plan.items.filter((i) => i.status === 'approved').length} changes shipped · Show
              </Button>
            )}
            {plan && plan.status === 'done' && !(editingLine && plan.status === 'done' && !showPlanWhileEditing) && (
              <ActivityLog plan={plan} />
            )}
            {plan && !clarifying && !(editingLine && plan.status === 'done' && !showPlanWhileEditing) && (
              <PlanCard
                plan={plan}
                speakers={speakers}
                voices={voices}
                projectId={project.project_id}
                busy={turnBusy}
                onAdjust={() => composerRef.current?.focus()}
                onRedo={(item) => redoTheItem(item)}
                onVoice={(id) => pickPlanVoice(id)}
              />
            )}
            {turnBusy && (
              <div className="flex items-center gap-2.5 text-sm text-muted-foreground" role="status" data-testid="turn-working">
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
                <span>{turnStep ?? 'Working…'}</span>
              </div>
            )}
          </ChatPanel>
        </aside>
        )}
      </div>
      <VoicesSheet
        open={voicesOpen}
        voices={myVoices}
        onUpload={async (name, file) => { await uploadMyVoice(name, file); takeInVoices(await listVoices()) }}
        onDelete={async (id) => { await deleteMyVoice(id); takeInVoices(await listVoices()) }}
        onClose={() => setVoicesOpen(false)}
      />
      {consentAsk && (
        <ConsentSheet who={consentAsk.who} busy={consenting} onConfirm={() => void confirmConsent()} onCancel={() => setConsentAsk(null)} />
      )}
      {shipped && (
        <ShipSheet
          shipped={shipped}
          busy={varianting}
          onVariant={() => void makeVariant()}
          onUndo={(item) => {
            if (!item.edit_id) return
            void revert(item.edit_id)
            setShipped((sh) => (sh ? { ...sh, items: sh.items.filter((i) => i.item_id !== item.item_id), held: sh.held + 1 } : sh))
          }}
          onClose={() => setShipped(null)}
        />
      )}
    </div>
  )
}
