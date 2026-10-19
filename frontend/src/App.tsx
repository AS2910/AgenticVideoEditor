import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { ConsentSheet } from './components/ConsentSheet'
import { Player, timecode } from './components/Player'
import type { Marker } from './components/Player'
import { captionAt, takeCaption } from './transcript/caption'
import type { CaptionPending } from './transcript/caption'
import { Timeline } from './components/Timeline'
import { VoltagePane } from './components/VoltagePane'
import { SpendPill } from './components/Spend'
import { LineDoc } from './components/LineDoc'
import type { LineRequest, PendingLine } from './components/LineDoc'
import type { LineKey } from './transcript/keys'
import { WhatVoltageMayDo } from './components/WhatVoltageMayDo'
import type { MayDo } from './components/WhatVoltageMayDo'
import { WhoSpeaks, EXAMPLES, SILENT_EXAMPLES } from './components/WhoSpeaks'
import { Wordmark, Wave } from './components/Wordmark'
import { Lanes } from './components/Lanes'
import { AccountDot } from './pages/Shell'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectPage } from './pages/ProjectPage'
import { MoveDialog } from './components/MoveDialog'
import { VoicesPage } from './pages/VoicesPage'
import { UsagePage } from './pages/UsagePage'
import { SettingsPage } from './pages/SettingsPage'
import { BillingPage } from './pages/BillingPage'
import { LoginPage } from './pages/LoginPage'
import { ExportPage } from './pages/ExportPage'
import { HelpPage } from './pages/HelpPage'
import { KeyboardSheet } from './components/KeyboardSheet'
import { TourProvider, TourLayer, useTour } from './tour/engine'
import { guidedRun, tourById } from './tour/tours'
import type { Tour } from './tour/types'
import { OnboardingProvider, useOnboarding } from './guides/onboarding'
import { Checklist } from './guides/Checklist'
import { Tip } from './guides/Tip'
import { go, hrefFor, useRoute } from './lib/route'
import { cn } from '@/lib/utils'
import { clock } from './transcript/format'
import {
  createProject, confirmPlace, exportProject, artifactUrl, pollJob, PollCancelled, ApiError, listVideos, listFolders, createFolder, startTutorial, getProject, deleteProject, getUsage, getSpend, listVoices, updateSpeaker, detectSpeakers, revertEdit, updateSettings, removeLine, dismissItem, setEditLevel, setCandidateLevel, BACKGROUND_DB, moveCandidate, moveEdit, getArrangement, putArrangement, undoArrangement, getPlan, approvePlan, readProject, grantConsent, getMe, postTurn, postAllowMore, getMessages,
} from './api'
import type { ArrangementView, Me, PlanApproval } from './api'
import type { Arrangement, Placed } from './transcript/arrange'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage,
  Insert, ProjectSummary, Usage, SpendSummary, Statement, Voice, Revision,
  Plan, PlanItem, Autonomy, Reading, Piece, ProjectDetail, ApprovedEditSummary, MyVoice, ProjectFolder, ExportManifest,
} from './types'
import { piecesFromInserts, renderTimeFrom, sourceTimeFrom } from './timeline/selection'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'

// What Voltage may do until the project says otherwise (the server's defaults).
const MAY_DO: MayDo = { autonomy: 'ask', turn_usd: 0.5, effort: 'high', ceiling_usd: 2 }

// The model's short name on the pane's header; an unknown id shows as it is.
const MODEL_NAMES: Record<string, string> = {
  'claude-opus-5-5': 'Opus 5.5', 'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-haiku-5-5': 'Haiku 5.5', 'claude-fable-5-1': 'Fable 5.1',
}

/** What a turn that shipped on its own left behind, for the note in the pane (replaces the ship sheet). */
interface ShippedNote { count: number; held: number; spendUsd: number }

/** The app (Tutorial map and Help, 2026-10-19): what a person has met so
 *  far, and the tour engine shared by the guided run and every Show me. */
export default function App() {
  return (
    <OnboardingProvider>
      <ToursSaved />
    </OnboardingProvider>
  )
}

function ToursSaved() {
  const { setTour } = useOnboarding()
  return (
    <TourProvider onProgress={setTour}>
      <Studio />
      <TourLayer />
    </TourProvider>
  )
}

/** The routes and the editor. */
function Studio() {
  const tour = useTour()
  const onboarding = useOnboarding()
  const route = useRoute()
  // Who is here (Phase 9c): null until the server says.
  const [me, setMe] = useState<Me | null>(null)
  const [signedOut, setSignedOut] = useState(false)

  // UX-3: consent is asked for in a sentence the first time a voice is about to be made.
  const [consentAsk, setConsentAsk] = useState<{ who: string | null; go: () => void } | null>(null)
  const [consenting, setConsenting] = useState(false)
  const consentGiven = useRef(false)

  const [shippedNote, setShippedNote] = useState<ShippedNote | null>(null)
  const [loading, setLoading] = useState(false)
  const [project, setProject] = useState<Project | null>(null)
  const [transcript, setTranscript] = useState<Word[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [, setSegments] = useState<Segment[]>([])
  const [, setInserts] = useState<Insert[]>([])
  const [pieces, setPieces] = useState<Piece[]>([])
  const [download, setDownload] = useState<{ url: string; filename: string } | null>(null)
  // Bug 1 (2026-10-19): renders are asked for per mode, and only the latest request's answer is taken.
  const renderSeq = useRef({ final: 0, proposals: 0 })
  const [renderPending, setRenderPending] = useState<{ final: number | null; proposals: number | null }>({ final: null, proposals: null })
  const exporting = renderPending.final !== null
  const [uploadShare, setUploadShare] = useState<number | null>(null)
  const [rendered, setRendered] = useState<{ url: string; duration: number } | null>(null)
  // 20e: which render plays — the final, the original, or the preview with the proposals mixed in.
  const [view, setView] = useState<'original' | 'final' | 'proposals'>('original')
  const [preview, setPreview] = useState<{ url: string; duration: number; pieces: Piece[]; key: string } | null>(null)
  const previewing = renderPending.proposals !== null
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  // Help (2026-10-19): a goal put in the box for the guided run; a tour waiting for its video to open; the ? sheet.
  const [seed, setSeed] = useState<{ text: string; id: number } | null>(null)
  const [pendingTour, setPendingTour] = useState<Tour | null>(null)
  const [keysOpen, setKeysOpen] = useState(false)
  const [undoneAfterExport, setUndoneAfterExport] = useState(false)
  // The guided run's step 5 moves on once the take was heard in place and Original was played.
  const heard = useRef({ take: false, original: false })
  const heardBoth = (what: 'take' | 'original') => {
    heard.current[what] = true
    if (heard.current.take && heard.current.original) tour.notify('heard-and-original')
  }
  // Folders (2026-10-19): the projects, for Home, the move dialog and the editor's crumb.
  const [folders, setFolders] = useState<ProjectFolder[]>([])
  const [moving, setMoving] = useState(false)
  const [crumbMenu, setCrumbMenu] = useState(false)
  const [usage, setUsage] = useState<Usage | null>(null)
  // Spend scopes: this turn, this video, its project, the month, and the one that stops paid work first.
  const [spend, setSpend] = useState<SpendSummary | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const asVoice = (v: MyVoice): Voice => ({ voice_id: v.voice_id, name: v.name, description: 'your voice', gender: null, accent: null, age: null, category: 'mine' })
  const takeInVoices = (r: { voices: Voice[]; mine?: MyVoice[] }) => {
    const mine = (r.mine ?? []).map(asVoice)
    setVoices([...mine, ...r.voices.filter((v) => !mine.some((m) => m.voice_id === v.voice_id))])
  }
  // As shot (2026-10-19): where the next file starts when a mode switch changes the clock, and the O key's flip.
  const [carry, setCarry] = useState<{ time: number; id: number } | null>(null)
  const flipRef = useRef<(() => void) | null>(null)
  const [seekRequest, setSeekRequest] = useState<{ time: number; id: number; play?: boolean; until?: number } | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [approved, setApproved] = useState<Revision[]>([])
  // The arrangement (2026-10-19): where every spoken line plays, and, while one is dragged, where they would.
  const [arranged, setArranged] = useState<ArrangementView | null>(null)
  const [arrangePreview, setArrangePreview] = useState<Placed[] | null>(null)
  const [autonomy, setAutonomy] = useState<Autonomy>('ask')
  const [mayDo, setMayDo] = useState<MayDo>(MAY_DO)
  const [mayDoOpen, setMayDoOpen] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [reading, setReading] = useState<Reading | null>(null)
  const [readingBusy, setReadingBusy] = useState(false)
  const wantReading = useRef(true)
  const readFor = useRef<string | null>(null)
  const [turnBusy, setTurnBusy] = useState(false)
  const [turnStep, setTurnStep] = useState<string | null>(null)
  const seenSeq = useRef(0)
  const [editingLine, setEditingLine] = useState<Statement | null>(null)
  const [playingTake, setPlayingTake] = useState<string | null>(null)
  const takeAudio = useRef<HTMLAudioElement | null>(null)
  const playingCandidate = useRef<Candidate | null>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  // Volt: the tracks panel under the scrubber, and the word-precise timeline inside it.
  const [tracksOpen, setTracksOpen] = useState(false)
  const [precise, setPrecise] = useState(false)
  const [placing, setPlacing] = useState<{ id: string; start: number; duration: number } | null>(null)
  const [placeDraft, setPlaceDraft] = useState<string | null>(null)
  const opening = useRef<string | null>(null)

  const refreshProjects = useCallback(async () => {
    try {
      const [videos, made] = await Promise.all([listVideos({ recent: 60 }), listFolders().catch(() => [] as ProjectFolder[])])
      setProjects(videos)
      setFolders(made)
    } catch {
      setProjects([]) // the list is a convenience; uploading still works
    }
  }, [])

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe({ mode: 'off', user: null }))   // an older server: open as before
  }, [])

  // A 401 anywhere means the session ended: back to the door.
  useEffect(() => {
    if (me?.mode === 'google' && error === 'Sign in to continue.') setSignedOut(true)
  }, [error, me])

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
    setSpend(null)
    setApproved([])
    setArranged(null)
    setArrangePreview(null)
    setAutonomy('ask')
    setMayDo(MAY_DO)
    setMayDoOpen(false)
    setPlan(null)
    setReading(null)
    setReadingBusy(false)
    setShippedNote(null)
    setConsentAsk(null)
    consentGiven.current = false
    setEditingLine(null)
    setPlayingTake(null)
    setPlacing(null)
    setTracksOpen(false)
    takeAudio.current?.pause()
  }

  useEffect(() => {
    if (!crumbMenu) return
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest('[data-crumb]')) setCrumbMenu(false) }
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [crumbMenu])

  // "/" puts the cursor in the box, from anywhere that is not already typing (UX-4).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const t = e.target as HTMLElement | null
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
        if (window.location.hash.startsWith('#v/') || /^#p\d/.test(window.location.hash)) { e.preventDefault(); setKeysOpen(true) }
        return
      }
      if ((e.key === 'o' || e.key === 'O') && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const t = e.target as HTMLElement | null
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
        if (flipRef.current) { e.preventDefault(); flipRef.current() }
        return
      }
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      const box = composerRef.current
      if (box) { e.preventDefault(); box.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const projectId = project?.video_id ?? null
  const signedIn = me !== null && (me.mode === 'off' || (me.user !== null && !signedOut))

  /** Re-reads what the project has spent; after anything that may have paid. */
  const refreshUsage = useCallback(async (id: string | null) => {
    if (!id) return
    // Both are informational; a failed read leaves the last value.
    await Promise.all([
      getUsage(id).then(setUsage).catch(() => {}),
      getSpend({ video: id }).then(setSpend).catch(() => {}),
    ])
  }, [])

  useEffect(() => { void refreshUsage(projectId) }, [projectId, refreshUsage])
  useEffect(() => {
    if (!projectId) return
    let live = true
    getArrangement(projectId).then((a) => { if (live) setArranged(a) }).catch(() => {})
    return () => { live = false }
  }, [projectId])

  // The voices, once a project is open: they don't change while the app is open.
  useEffect(() => {
    if (!projectId || voices.length > 0) return
    listVoices()
      .then(takeInVoices)
      .catch(() => {}) // without the list, the editor offers no voice to pick
  }, [projectId, voices.length])

  // When a fresh project opens, Voltage takes the clip in once: an opening
  // line and a role for each speaker (UX-2), as its first message (UX-7c).
  useEffect(() => {
    if (!projectId || !wantReading.current || reading || readFor.current === projectId) return
    readFor.current = projectId
    setReadingBusy(true)
    readProject(projectId)
      .then((r) => setReading(r))
      .catch(() => {})   // the stage still works with the plain count
      .finally(() => { setReadingBusy(false); void refreshUsage(projectId) })
  }, [projectId, reading, project?.statements?.length, refreshUsage])

  /** Into the project: fresh ones start by asking what the video should
   *  say; ones with a plan or edits open straight in the editor. */
  const takeIn = (loaded: Project, edited = false) => {
    setProject(loaded)
    consentGiven.current = !!loaded.consent_granted_at
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
    opening.current = loaded.video_id
    go({ page: 'editor', projectId: loaded.video_id })
  }

  const load = async (file: File, projectId: string | null = null) => {
    setLoading(true)
    setUploadShare(0)
    setError(null)
    try {
      takeIn(await createProject(file, false, setUploadShare, projectId))
    } catch (e) {
      // The backend's rejection reason is the useful part — show it verbatim.
      setError(e instanceof ApiError ? e.message : 'Could not upload that video.')
    } finally {
      setLoading(false)
      setUploadShare(null)
    }
  }

  const startGuidedRun = async () => {
    setError(null)
    try {
      const video = await startTutorial()
      heard.current = { take: false, original: false }
      setPendingTour(guidedRun)
      takeIn(video)
      setSeed({ text: 'Make the offer 30% off', id: Date.now() })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the tour.')
    }
  }
  /** Show me: a short feature tour on the video that is open, else on the most recent one. */
  const showMe = (id: string) => {
    const t = tourById(id)
    if (!t) return
    if (id === 'save-voice') { go({ page: 'voices' }); window.setTimeout(() => tour.start(t, 0), 300); return }
    if (project && (route.page === 'editor')) { tour.start(t, 0); return }
    const recent = projects[0]
    if (recent) { setPendingTour(t); go({ page: 'editor', projectId: recent.video_id }) } else void startGuidedRun()
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
      setProject((p) => (p ? { ...p, consent_granted_at: r.consent_granted_at } : p))
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
        rev.edit_id === editId ? { ...rev, edit_id: r.edit_id, start: at.start, end: at.end, text, mix, partner: rev.partner ?? null }
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
      const seq = beginRender('final')
      let result: PlanApproval | null = null
      try {
        result = await approvePlan(projectId, plan.plan_id, passed ? { items: [item.item_id] } : { items: [item.item_id], override: true })
        takeInApproval(result, seq)
      } finally {
        endRender('final', seq, result?.export ?? null)
      }
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
  /** The arrangement, as one action: saved, then the video rendered with it. */
  const arrange = async (next: Arrangement | 'undo') => {
    if (!projectId) return
    setError(null)
    try {
      setArranged(next === 'undo' ? await undoArrangement(projectId) : await putArrangement(projectId, next))
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
    audio.src = artifactUrl(project.video_id, c.audio.sha256)
    audio.onended = () => { setPlayingTake(null); playingCandidate.current = null }
    playingCandidate.current = c
    const span = c.plan.selection
    // Over the final only when it is the render of the edits now (no newer one pending); else over the original.
    const overFinal = rendered !== null && renderPending.final === null && pieces.every((p) => p.kind === 'copy')
    setView(overFinal ? 'final' : 'original')
    setSeekRequest((r) => ({ time: span.start, id: (r?.id ?? 0) + 1, play: true, until: span.start + c.audio.duration + 0.3 }))
    setCurrentTime(span.start)
    setPlayingTake(c.candidate_id)
    heardBoth('take')
    const started = audio.play() as Promise<void> | undefined
    if (started && typeof started.catch === 'function') started.catch(() => {})
  }

  const rememberAutonomy = async (value: Autonomy) => {
    onboarding.markChecklist('autonomy')
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
    onboarding.markChecklist('autonomy')
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
      setPlaceDraft(null)
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't keep that place. Try again.")
    }
  }

  /** A goal for the whole video, an answer to Voltage's question, or a change
   *  to the plan: every one is a turn (20c; the form planner is gone). */
  const clarify = (answer?: string, allowMore = false) => {
    if (!plan?.question) return
    return takeTurn(answer ?? plan.question.guess ?? plan.question.options[0], false, allowMore && !!plan.question.turn_cap)
  }

  /** The box is for the whole video: a goal, a change to the plan, an answer.
   *  With words selected on the Precise timeline, the sentence names the time. */
  const submitComposer = (text: string) => void takeTurn(selection && precise ? `At ${clock(selection.start)}: ${text}` : text)

  /** Phase 20: one turn of Voltage with tools. The steps arrive as messages
   *  while it works; the result is the plan and Voltage's closing line. A
   *  paid step needs the project's consent (UX-3): asked before the turn
   *  under Just do it, and when the server asks for it (403) under Check
   *  with me — then the same turn goes again, once. */
  const takeTurn = async (text: string, again = false, allowMore = false) => {
    if (!projectId) return
    if (autonomy === 'draft' && !consentGiven.current) return withConsent(null, () => void takeTurn(text, again, allowMore))
    if (!again) say({ role: 'user', text })
    setError(null)
    setShippedNote(null)
    setTurnBusy(true)
    setTurnStep('Thinking…')
    try {
      // "Go ahead, allow $0.04 more": this turn's cap rises by exactly that and the same turn carries on.
      const job = allowMore ? await postAllowMore(projectId) : await postTurn(projectId, text)
      tour.notify('turn-started')
      await followTurn(job.job_id)
    } catch (e) {
      setTurnBusy(false)
      setTurnStep(null)
      if (e instanceof ApiError && e.status === 403 && !consentGiven.current && !again) {
        return withConsent(null, () => void takeTurn(text, true, allowMore))
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
      const result = finished.result as { type?: string; plan?: Plan; spend?: SpendSummary } | null
      if (result?.spend) setSpend(result.spend)
      let fresh: Plan | null = null
      if (result && result.type === 'turn' && result.plan) fresh = result.plan
      else {
        const latest = await getProject(projectId).catch(() => null)
        if (latest?.plan) fresh = latest.plan
      }
      if (fresh) {
        setPlan(fresh)
        await takeInShipped(fresh)
        if (fresh.question) tour.notify(fresh.question.gate ? 'gate-shown' : 'question-shown')
        if (fresh.items.some((i) => i.status === 'ready' && i.candidate)) tour.notify('take-ready')
      }
      if (finished.status === 'succeeded' && !project?.settings?.tutorial) onboarding.markChecklist('goal')
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

  /** An approved edit as the transcript shows it (20g: with its level; Volt: with its speaker and voice). */
  const asRevision = (e: ApprovedEditSummary): Revision => ({
    edit_id: e.edit_id, start: e.selection.start, end: e.selection.end, text: e.new_text, mix: e.mix, partner: e.partner ?? null, level_db: e.level_db ?? null,
    speaker: e.speaker ?? null, voice_profile_id: e.voice_profile_id ?? null,
  })
  /** The plan item just approved, as a revision. */
  const itemRevision = (i: PlanItem): Revision => ({
    edit_id: i.edit_id!, start: i.candidate?.plan.selection.start ?? i.selection.start,
    end: i.candidate?.plan.selection.end ?? i.selection.end, text: i.new_text, mix: i.mix, level_db: i.candidate?.plan.level_db ?? null,
    speaker: i.speaker ?? null, voice_profile_id: i.candidate?.plan.voice_profile_id ?? null,
  })

  /** 20g: after a turn, the edits as the server has them — Voltage may have undone or releveled a line — so the transcript never shows a stale row. */
  const syncEdits = async (): Promise<{ changed: boolean; render: { download: { url: string; filename: string }; duration: number } | null }> => {
    if (!projectId) return { changed: false, render: null }
    const latest = await getProject(projectId).catch(() => null)
    if (!latest) return { changed: false, render: null }
    // p60: the items too, not only the edits, so the rows, the header's counts and Voltage's words come from one record.
    if (latest.plan) setPlan(latest.plan)
    const live = latest.edits.filter((e) => !e.reverted).map(asRevision)
    const before = approved.map((r) => r.edit_id).sort().join(',')
    const after = live.map((r) => r.edit_id).sort().join(',')
    setApproved(live)
    // Voltage may have moved a line (shift_line pins it): the arrangement is part of what plays.
    const nextArrangement = await getArrangement(projectId).catch(() => null)
    const moved = (v: ArrangementView | null) => JSON.stringify(v?.lines.map((l) => [l.key, l.start]) ?? [])
    const rearranged = nextArrangement !== null && moved(nextArrangement) !== moved(arranged)
    if (nextArrangement) setArranged(nextArrangement)
    if (before === after && !rearranged) return { changed: false, render: null }
    setPreview(null)
    if (live.length === 0 && !nextArrangement?.lines.some((l) => l.moved)) { setRendered(null); setDownload(null); setSegments([]); setInserts([]); setPieces([]); setView('original'); return { changed: true, render: null } }
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
  const takeInApproval = (result: PlanApproval, seq: number) => {
    setPlan(result.plan)
    setPreview(null)
    const fresh = result.plan.items.filter((i) => i.status === 'approved' && i.edit_id
      && !approved.some((r) => r.edit_id === i.edit_id))
    setApproved((a) => [...a, ...fresh.map(itemRevision)])
    if (fresh.length > 0) { tour.notify('added'); onboarding.markChecklist('add') }
    // The approval's render is taken only if no newer final render was asked for meanwhile.
    if (!result.export || !projectId || !isLatest('final', seq)) return null
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
   *  switches to it and a note in the pane says what went in (Volt: the
   *  export page has the receipt). */
  const takeInShipped = async (fresh: Plan) => {
    if (!projectId) return
    const went = fresh.items.filter((i) => i.status === 'approved' && i.edit_id
      && !approved.some((r) => r.edit_id === i.edit_id))
    const { changed, render } = await syncEdits()
    if (went.length === 0 || !changed || !render) return
    setShippedNote({ count: went.length, held: fresh.items.filter((i) => i.status === 'ready').length, spendUsd: fresh.spend_usd })
  }

  /** Add them all (20e): every proposal goes into the video in one render,
   *  flagged takes included — the user asked for all of them. */
  const approveAll = async (items: PlanItem[]) => {
    if (!projectId || !plan) return
    setError(null)
    const seq = beginRender('final')
    let manifest: ExportManifest | null = null
    try {
      const result = await approvePlan(projectId, plan.plan_id, {
        items: items.map((i) => i.item_id), override: items.some((i) => !(i.candidate?.continuity.passed ?? true)),
      })
      manifest = result.export ?? null
      takeInApproval(result, seq)
      setPreview(null)
      if (result.skipped.length > 0) {
        setError(`${result.skipped.length} ${result.skipped.length === 1 ? 'line was' : 'lines were'} not added. Hear them, then Add it one by one or ask for another take.`)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not add those lines.')
    } finally {
      endRender('final', seq, manifest)
      void refreshUsage(projectId)
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
      if (download) setUndoneAfterExport(true)
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
    if (!projectId) return
    const key = (plan?.items ?? []).filter((i) => i.kind === 'planned' && i.status === 'ready').map((i) => i.candidate?.candidate_id ?? i.item_id).join(',')
    if (preview && preview.key === key) return
    setError(null)
    const seq = beginRender('proposals')
    let manifest: ExportManifest | null = null
    try {
      manifest = await exportProject(projectId, true, seq)
      if (!isLatest('proposals', seq)) return
      const url = artifactUrl(projectId, manifest.render.sha256)
      setPreview({ url, duration: manifest.render.duration, key,
        pieces: manifest.pieces ?? piecesFromInserts(manifest.inserts ?? [], project?.duration ?? 0) })
    } catch {
      if (isLatest('proposals', seq)) {
        setError('Could not render the preview with the proposals.')
        setView(rendered ? 'final' : 'original')
      }
    } finally {
      endRender('proposals', seq, manifest)
    }
  }

  /** A render asked for: its id, the latest for its mode. */
  const beginRender = (mode: 'final' | 'proposals') => {
    const seq = ++renderSeq.current[mode]
    setRenderPending((p) => ({ ...p, [mode]: seq }))
    console.debug('[render] request', { mode, seq })
    return seq
  }
  /** Its answer: taken only when no newer request for the mode was made since; the status clears with the latest. */
  const isLatest = (mode: 'final' | 'proposals', seq: number) => seq === renderSeq.current[mode]
  const endRender = (mode: 'final' | 'proposals', seq: number, manifest?: ExportManifest | null) => {
    const latest = isLatest(mode, seq)
    console.debug(latest ? '[render] take' : '[render] drop (stale)', { mode, seq, hash: manifest?.edit_hash, sha: manifest?.render.sha256.slice(0, 12), cached: manifest?.cached })
    if (latest) setRenderPending((p) => ({ ...p, [mode]: null }))
    return latest
  }

  /** Renders the approved edits; the render (and its download) once it is ready to play, else null. */
  const runExport = async (
    id: string | null = projectId, filename = project?.filename,
  ): Promise<{ download: { url: string; filename: string }; duration: number } | null> => {
    if (!id) return null
    setError(null)
    const seq = beginRender('final')
    let manifest: ExportManifest | null = null
    try {
      manifest = await exportProject(id, false, seq)
      // An older render that finishes after a newer one was asked for is dropped: it no longer matches the edits.
      if (!isLatest('final', seq)) return null
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
      if (isLatest('final', seq)) setError('Export failed.')
      return null
    } finally {
      endRender('final', seq, manifest)
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
      if (live.length > 0 && await runExport(opened.video_id, opened.filename)) {
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

  // Volt: the route decides what is open. The editor and export routes open
  // the project they name (once, by id); the start lists the projects and
  // lets the last one go.
  useEffect(() => {
    if (!signedIn) return
    if (route.page === 'editor' || route.page === 'export') {
      if (opening.current !== route.projectId) { opening.current = route.projectId; void openProject(route.projectId) }
    } else if (route.page === 'projects' || route.page === 'folder') {
      if (project) { clearEditor(); opening.current = null }
      void refreshProjects()
    }
    // openProject and clearEditor are stable enough for the route's purposes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, signedIn])

  useEffect(() => {
    if (!pendingTour || !project || route.page !== 'editor') return
    const t = pendingTour
    setPendingTour(null)
    // One frame for the rows to be on the page before the ring measures them.
    window.setTimeout(() => tour.start(t, t.id === guidedRun.id ? undefined : 0), 50)
  }, [pendingTour, project, route.page, tour])
  useEffect(() => {
    if (route.page === 'export') { tour.notify('export-opened'); onboarding.markChecklist('export') }
  }, [route.page]) // eslint-disable-line react-hooks/exhaustive-deps

  const signedOutNow = () => {
    clearEditor()
    opening.current = null
    setMe((m) => (m ? { ...m, user: null } : m))
    go({ page: 'projects' })
  }

  const page = (() => {
  if (me === null) {
      return (
        <div className="flex min-h-dvh items-center justify-center gap-3 bg-background text-muted-foreground" role="status" aria-busy="true">
          <Wave busy /><span>Opening…</span>
        </div>
      )
    }
    if (me.mode === 'google' && (!me.user || signedOut)) {
      return <LoginPage error={signedOut ? 'Your session ended. Sign in again to continue.' : null} />
    }
    if (route.page === 'projects') {
      return (
        <ProjectsPage
          me={me}
          projects={projects}
          folders={folders}
          onOpen={(id) => go({ page: 'editor', projectId: id })}
          onUpload={(file, pid) => void load(file, pid)}
          onSample={() => void loadSample()}
          onDelete={(id) => void removeProject(id)}
          onNewFolder={async (name) => { const made = await createFolder(name); await refreshProjects(); return made }}
          onFolderMade={() => void refreshProjects()}
          onMoved={() => void refreshProjects()}
          banner={onboarding.loaded && !onboarding.onboarding.tour.finished && !onboarding.onboarding.tour.skipped ? (
            <div className="rise flex flex-wrap items-center gap-4 rounded-xl bg-pane px-5 py-4 text-ptext shadow-volt" data-testid="tour-offer">
              <span className="flex flex-1 basis-[260px] flex-col gap-0.5">
                <span className="disp text-lg font-bold">New here? Make one real edit in three minutes.</span>
                <span className="pm text-sm">On our sample ad, free: nothing is voiced or spent.</span>
              </span>
              <button type="button" className="btn volt sm shine" onClick={() => void startGuidedRun()}>⚡ Start the tour</button>
              <button type="button" className="btn ghost sm" onClick={() => onboarding.setTour({ ...onboarding.onboarding.tour, skipped: true })}>Not now</button>
            </div>
          ) : undefined}
          uploading={loading}
          progress={uploadShare}
          error={error}
        />
      )
    }
    if (route.page === 'folder') {
      return <ProjectPage me={me} projectId={route.projectId} onUpload={(file, pid) => void load(file, pid)} uploading={loading} error={error} onDeleted={() => void refreshProjects()} />
    }
    if (route.page === 'help') {
      return <HelpPage me={me} initialSlug={route.slug ?? null} onReplay={() => void startGuidedRun()} onAsk={() => { const recent = projects[0]; if (recent) go({ page: 'editor', projectId: recent.video_id }); else go({ page: 'projects' }) }} onShowMe={showMe} />
    }
    if (route.page === 'voices') return <VoicesPage me={me} />
    if (route.page === 'usage') return <UsagePage me={me} scope={route.scope ?? null} />
    if (route.page === 'settings') return <SettingsPage me={me} onSignedOut={signedOutNow} />
    if (route.page === 'billing') return <BillingPage me={me} />
    if (route.page === 'export') {
      return <ExportPage projectId={route.projectId} me={me} onBack={() => go({ page: 'editor', projectId: route.projectId })} />
    }
    if (!project) {
      return (
        <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background px-4 text-center" role={error ? undefined : 'status'} aria-busy={!error || undefined}>
          {error ? (
            <>
              <p className="disp m-0 text-xl font-bold" role="alert">{error}</p>
              <a className="btn sm" href={hrefFor({ page: 'projects' })}>← Projects</a>
            </>
          ) : <><Wave busy /><span className="text-muted-foreground">Opening {route.page === 'editor' ? route.projectId : 'the video'}…</span></>}
        </div>
      )
    }
  
    const speakers = project.speakers ?? []
    // 20f: the spoken lines only; added lines and proposals are rows of their own in LineDoc.
    const statements: Statement[] = project.statements ?? []
    // Where each spoken line plays now (by its place in the transcript): the drag's preview while one is dragged, else the arrangement.
    const placedSpans: ({ start: number; end: number } | undefined)[] = (() => {
      const placed = arrangePreview ?? arranged?.lines ?? null
      if (!placed || (arranged && arranged.lines.length !== statements.length)) return []
      const out: ({ start: number; end: number } | undefined)[] = []
      for (const p of placed) out[Number(p.key.slice(1))] = { start: p.start, end: p.end }
      return out
    })()
  
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
    const clarifying = plan?.status === 'clarifying'
    const needsYou = planItems.filter((i) => i.status === 'needs-you')
    const stateWord = clarifying ? 'needs your go'
      : turnBusy ? 'working'
      : readingBusy ? 'reading'
      : editingLine ? 'standing by'
      : readyItems.length > 0 ? `${readyItems.length} proposed`
      : 'ready'
    const sendLabel = clarifying ? 'Answer' : 'Send'
    const placeholder = clarifying ? 'Answer, or tell Voltage anything else'
      : selection && precise ? 'Ask for a change, e.g. say "30% off" instead'
      : plan ? 'Say what to change, or ask for another take'
      : 'What should this video say?'
    // The first read (Volt): nothing said yet — the opening line, who speaks, the examples.
    const firstRead = !plan && messages.length === 0
    const engine = [project.settings?.model ? (MODEL_NAMES[project.settings.model] ?? project.settings.model) : null, mayDo.effort].filter(Boolean).join(' · ')
  
    const sourceClock = shown ? sourceTimeFrom(currentTime, shown.pieces) : currentTime
    const voiceLine = usage?.lines.find((l) => l.vendor === 'elevenlabs' && l.units > 0)
    const usdPerChar = voiceLine ? voiceLine.usd / voiceLine.units : null
    const playingMix = playingTake
      ? (playingCandidate.current?.candidate_id === playingTake ? playingCandidate.current.plan.mix : null)
        ?? plan?.items.find((i) => i.candidate?.candidate_id === playingTake)?.candidate?.plan.mix ?? 'replace'
      : null
    // UX-7b: the monitor's clock follows the version that plays: an insert in
    // the edited render pushes everything after it later.
    const toRender = (t: number) => (shown ? renderTimeFrom(t, shown.pieces) : t)
    // Volt: the scrubber's marks — a proposal (volt), a line in the video (ink), a step waiting on you (amber).
    const markers: Marker[] = [
      ...approved.filter((r) => r.mix !== 'remove').map((r) => ({ at: toRender(r.start), tone: 'ink' as const, label: `In the video: ${r.text}` })),
      ...readyItems.filter((i) => i.candidate).map((i) => ({ at: toRender(i.candidate!.plan.selection.start), tone: 'volt' as const, label: `Proposed: ${i.new_text}` })),
      ...needsYou.map((i) => ({ at: toRender(i.selection.start), tone: 'warn' as const, label: `Waiting on you: ${i.new_text}` })),
    ]
    // A take in hand, not yet kept, is captioned with its words too: the picture
    // shows what you are about to hear.
    const takesInHand: CaptionPending[] = readyItems.flatMap((i) => (
      i.candidate ? [{ selection: i.candidate.plan.selection, text: i.candidate.plan.new_text, mix: i.candidate.plan.mix }] : []
    ))
    const captionRuns = captionAt(sourceClock, statements, approved, [...pendingLines, ...takesInHand], transcript, rendered !== null && view === 'original', placedSpans)
    // A take playing in place with word times (the polish pass): its words, lit as they are said.
    const spoken = playingTake && playingCandidate.current?.candidate_id === playingTake && playingCandidate.current.words?.length
      ? takeCaption(playingCandidate.current.words, currentTime - playingCandidate.current.plan.selection.start)
      : null
    const caption = spoken
      ? spoken.map((w, k) => <Fragment key={k}>{k > 0 && ' '}<ins data-said={w.said || undefined}>{w.text}</ins></Fragment>)
      : captionRuns?.map((r, k) => <Fragment key={k}>{k > 0 && ' '}{r.kind === 'ins' ? <ins>{r.text}</ins> : r.text}</Fragment>)
  
    // As shot (2026-10-19): Edited has the live edits, As shot is the source as shot, With proposals adds
    // what is waiting. With no live edits Edited is As shot, so it is not offered.
    const changes = approved.filter((r) => !(r.mix === 'remove' && r.partner)).length
    const views = [
      ...(changes > 0 ? [['final', 'Edited'] as const] : []),
      ...(readyItems.length > 0 ? [['proposals', 'With proposals'] as const] : []),
      ['original', 'As shot'] as const,
    ]
    const proposalsWord = `${readyItems.length} ${readyItems.length === 1 ? 'proposal' : 'proposals'}`
    const badge = view === 'original'
      ? (changes > 0 ? `As shot · ${changes} ${changes === 1 ? 'change' : 'changes'} hidden` : 'As shot')
      : view === 'final'
        ? (readyItems.length > 0 ? `Edited · ${proposalsWord} not included` : 'Edited')
        : 'With proposals'
    const version = view === 'original' ? 'as-shot' as const : view === 'proposals' ? 'proposals' as const : 'edited' as const
    /** Switch modes at the same moment, playing or paused: the time is carried across, mapped through the pieces when the clocks differ. */
    const switchView = (v: typeof view) => {
      if (v === view) return
      const piecesOf = (w: typeof view) => (w === 'final' && rendered ? pieces : w === 'proposals' && previewReady ? preview!.pieces : [])
      const source = shown ? sourceTimeFrom(currentTime, shown.pieces) : currentTime
      const next = piecesOf(v)
      const time = next.length ? renderTimeFrom(source, next) : source
      setCarry((c) => ({ time, id: (c?.id ?? 0) + 1 }))
      setView(v)
      if (v === 'proposals') void ensurePreview()
      if (v === 'original') heardBoth('original')
    }
    // O flips Edited ↔ As shot (from With proposals, to As shot).
    flipRef.current = route.page === 'editor' && changes > 0 ? () => switchView(view === 'original' ? 'final' : 'original') : null
    const scanning = turnBusy ? (turnStep ?? 'Voltage is working') : readingBusy ? 'Voltage is reading the clip' : null
    const isTutorial = !!project.settings?.tutorial
    const tipCandidates: { id: string; target: string; when: boolean }[] = [
      { id: 'first-failed-take', target: 'transcript-row', when: planItems.some((i) => i.status === 'failed') },
      { id: 'first-ceiling', target: 'spend', when: !!error && /ceiling/i.test(error) },
      { id: 'first-question', target: 'question', when: !!clarifying && !plan?.question?.gate },
      { id: 'first-voice-design', target: 'composer', when: messages.some((m) => m.kind === 'previews') },
      { id: 'first-undo-after-export', target: 'export', when: undoneAfterExport },
      { id: 'first-background', target: 'transcript-row', when: approved.some((r) => (r.level_db ?? 0) < 0) },
      { id: 'first-just-do-it', target: 'autonomy', when: autonomy === 'draft' },
      { id: 'first-silent', target: 'composer', when: !isTutorial && firstRead && statements.length === 0 },
      { id: 'first-upload', target: 'composer', when: !isTutorial && firstRead && statements.length > 0 && !readingBusy },
    ]
    const firstTip = tour.tour || !onboarding.loaded ? null : tipCandidates.find((t) => t.when && !onboarding.onboarding.tips.includes(t.id)) ?? null
    const folderOf = project.project_id ? folders.find((f) => f.project_id === project.project_id) ?? null : null
    // The pane says what project context Voltage is reading, so its choices are never a mystery.
    const contextChips = project.project_id
      ? [`Brief · ${project.project_name ?? 'project'}`, ...(folderOf?.voices ? [`${folderOf.voices} shared ${folderOf.voices === 1 ? 'voice' : 'voices'}`] : []), ...(folderOf?.files ? [`${folderOf.files} ${folderOf.files === 1 ? 'file' : 'files'}`] : [])]
      : []
    const sight = reading?.sight ?? null
    const place = sight ? (sight.place_confirmed ?? sight.place_guess) : null
  
    return (
      <div className="flex h-dvh flex-col bg-background text-foreground max-[960px]:h-auto max-[960px]:min-h-dvh">
        <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to the transcript</a>
        {/* Volt: the editor's header — the wordmark, the file, the play switch, the autonomy, the spend, Export, the account. */}
        <header className="flex min-h-[62px] flex-wrap items-center gap-x-4 gap-y-2 border-b-[1.5px] border-foreground bg-card px-4 py-2 sm:px-6 lg:flex-nowrap lg:[&>*:not(h1)]:shrink-0" data-testid="editor-header">
          <Wordmark />
          <span className="text-faint max-sm:hidden" aria-hidden="true">/</span>
          {/* Folders: the project the video is in, with its menu; or a dashed "No project" that opens the move dialog. */}
          <div className="relative" data-crumb>
            {project.project_id ? (
              <button type="button" className="inline-flex h-[34px] items-center gap-2 rounded-lg border-[1.5px] border-line2 bg-card px-2.5 font-semibold hover:border-foreground" aria-haspopup="menu" aria-expanded={crumbMenu} onClick={() => setCrumbMenu((m) => !m)} data-testid="crumb">
                <span aria-hidden="true" className="h-3 w-4 rounded-[3px] border-[1.5px] border-ink bg-volt" />{project.project_name ?? 'Project'}<span aria-hidden="true" className="text-xs">▾</span>
              </button>
            ) : (
              <button type="button" className="inline-flex h-[34px] items-center gap-2 rounded-lg border-[1.5px] border-dashed border-line2 bg-card px-2.5 font-medium text-muted-foreground hover:border-foreground" onClick={() => setMoving(true)} data-testid="crumb">
                <span aria-hidden="true" className="h-3 w-4 rounded-[3px] border-[1.5px] border-dashed border-current" />No project · Add to project
              </button>
            )}
            {crumbMenu && project.project_id && (
              <div role="menu" className="rise absolute left-0 z-20 mt-1 flex w-80 flex-col rounded-xl border-[1.5px] border-ink bg-card p-2 shadow-volt" data-testid="crumb-menu">
                <a role="menuitem" className="act justify-start gap-2.5" href={hrefFor({ page: 'folder', projectId: project.project_id })} onClick={() => setCrumbMenu(false)}>
                  <span aria-hidden="true" className="h-3 w-4 rounded-[3px] border-[1.5px] border-current" /><span className="flex-1">Open {project.project_name}</span>
                  {folderOf && <span className="tag text-faint">{folderOf.video_count ?? 0} {folderOf.video_count === 1 ? 'video' : 'videos'}</span>}
                </a>
                <button type="button" role="menuitem" className="act justify-start gap-2.5" onClick={() => { setCrumbMenu(false); setMoving(true) }}><span aria-hidden="true" className="w-4 text-center">↗</span>Move to project…</button>
                <div className="mx-1 mt-1.5 mb-1 flex flex-col gap-1 rounded-lg bg-sunk p-2.5">
                  <span className="tag text-faint">Brief Voltage is using</span>
                  <span className="line-clamp-3 text-[13px]">{folderOf?.brief?.trim() ? folderOf.brief : 'No brief yet.'}</span>
                  <a className="tag text-foreground no-underline" href={hrefFor({ page: 'folder', projectId: project.project_id })} onClick={() => setCrumbMenu(false)}>Edit brief →</a>
                </div>
              </div>
            )}
          </div>
          <span className="text-faint max-sm:hidden" aria-hidden="true">/</span>
          <h1 className="disp m-0 min-w-0 max-w-[28ch] truncate text-[15px] font-semibold lg:max-w-none lg:flex-[1_1_0]" title={project.filename}>{project.filename}</h1>
          <span className="tag text-faint">{timecode(project.duration)}{speakers.length > 0 ? ` · ${speakers.length} ${speakers.length === 1 ? 'voice' : 'voices'}` : ''}</span>
          {views.length > 1 ? (
            <div className="segs" role="group" aria-label="Play" data-tour="playback-switch">
              {views.map(([v, label]) => (
                <button key={v} type="button" className="seg" aria-pressed={view === v} onClick={() => switchView(v)}
                  title={v === 'final' ? 'The video with the lines you added (O)' : v === 'original' ? 'The video as shot, without your changes (O)' : 'Edited, plus the proposals waiting for you'}>
                  {v === 'proposals' && !previewReady && previewing ? `${label}…` : label}
                </button>
              ))}
            </div>
          ) : (
            <span className="tag rounded-md border-[1.5px] border-line2 px-2.5 py-1.5 text-muted-foreground" data-testid="as-shot-label" title="Nothing is changed yet: the video plays as shot.">As shot</span>
          )}
          <span className="flex-1" />
          <button type="button" className="act" onClick={() => { setMayDoOpen(true); tour.notify('autonomy-opened') }} data-tour="autonomy" data-tour-action="autonomy" aria-haspopup="dialog" aria-label={`${autonomy === 'ask' ? 'Check with me' : 'Just do it'}. What Voltage may do`}>
            <span className="tag">{autonomy === 'ask' ? 'Check with me' : 'Just do it'}</span>
            <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
          <SpendPill summary={spend} videoId={project.video_id} />
          <a className={cn('btn ink sm', exporting && 'opacity-70')} href={hrefFor({ page: 'export', projectId: project.video_id })} aria-busy={exporting || undefined} data-tour="export" data-tour-action="export">
            {exporting ? 'Rendering…' : 'Export'}
          </a>
          <AccountDot me={me} />
          <WhatVoltageMayDo open={mayDoOpen} value={mayDo} onChange={(c) => void changeMayDo(c)} onClose={() => setMayDoOpen(false)} />
        </header>
  
        <div className="flex min-h-0 flex-1 max-[960px]:flex-col">
          {/* The picture, the transport, the transcript. */}
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 overflow-y-auto outline-none max-[960px]:overflow-visible" aria-busy={turnBusy || undefined}>
            <div className="mx-auto flex w-full max-w-[820px] flex-col gap-4 px-4 py-5 sm:px-6">
              <Player
                src={shown ? shown.url : artifactUrl(project.video_id, project.media.sha256)}
                duration={shown ? shown.duration : project.duration}
                currentTime={currentTime}
                onSeek={setCurrentTime}
                onTimeUpdate={setCurrentTime}
                seekRequest={seekRequest}
                caption={caption}
                muted={playingTake !== null && playingMix === 'replace'}
                badge={badge}
                carry={carry}
                scanning={scanning}
                markers={markers}
                bigPlay={firstRead}
              >
                <button type="button" className="act" aria-expanded={tracksOpen} aria-controls="tracks" onClick={() => setTracksOpen((t) => !t)}>
                  <span className="tag">Tracks</span>
                  <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" className={cn('transition-transform', tracksOpen && 'rotate-180')}><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </button>
              </Player>
              {tracksOpen && (
                <section id="tracks" className="flex flex-col gap-3 rounded-xl border-[1.5px] border-line2 bg-card p-4" aria-label="Tracks">
                  <Lanes
                    duration={project.duration}
                    currentTime={sourceClock}
                    statements={statements}
                    placedAt={version === 'as-shot' ? undefined : placedSpans}
                    speakers={speakers}
                    revisions={approved}
                    asShot={version === 'as-shot'}
                    items={planItems}
                    pieces={shown?.pieces ?? pieces}
                    onSeek={(t) => { const time = shown ? renderTimeFrom(t, shown.pieces) : t; setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 })); setCurrentTime(time) }}
                    placing={placing}
                    onPlace={(start) => setPlacing((p) => (p ? { ...p, start } : p))}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" className="pill" aria-pressed={precise} onClick={() => setPrecise((p) => !p)}>Precise</button>
                    <span className="meta">{precise ? 'Pick words on the timeline; the box then talks about that moment.' : 'Word by word, when you need it.'}</span>
                    <span className="flex-1" />
                    <span className="tag text-faint" role="status" aria-busy={previewing || undefined} data-testid="retime">
                      {view === 'proposals' && !previewReady ? (previewing ? 'Rendering with the proposals…' : 'The proposals changed; rendering again…')
                        : view === 'proposals' ? `Preview mix · ${readyItems.length} proposed ${readyItems.length === 1 ? 'take' : 'takes'}`
                        : view === 'final' && rendered ? 'The final' : 'The original'}
                      {shown && shown.pieces.some((p) => p.kind === 'flex' && p.factor != null && Math.abs(p.factor - 1) > 0.005) && ' · picture flexed'}
                    </span>
                  </div>
                  {precise && (
                    <Timeline key={project.video_id} words={transcript} duration={project.duration} selection={selection} currentTime={sourceClock} onSelect={setSelection} />
                  )}
                </section>
              )}
              {error && <div className="rounded-lg border-[1.5px] border-warn bg-card px-3.5 py-2.5 text-sm" role="alert">{error}</div>}
              {firstRead && speakers.length > 0 && (
                <WhoSpeaks speakers={speakers} statements={statements} reading={readingBusy ? null : reading} onName={(label, name) => void changeSpeaker(label, { name })} />
              )}
              {firstRead && speakers.length === 0 && statements.length > 0 && (
                <div className="flex items-center gap-3 rounded-xl border-[1.5px] border-line2 bg-card p-4">
                  <span className="meta flex-1">Voltage hasn't told the speakers apart yet.</span>
                  <button type="button" className="btn sm" onClick={() => void findSpeakers()} disabled={detecting} aria-busy={detecting || undefined}>{detecting ? 'Listening…' : 'Find who speaks'}</button>
                </div>
              )}
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
            onRetry={(item) => void takeTurn(`Try ${item.item_id} again (“${item.new_text}”): ${item.error ?? 'the last try failed'}`)}
                onUndo={(id) => void revert(id)}
                onRemove={(s) => void removeStatement(s)}
                arranged={arranged}
                onArrange={(next) => arrange(next)}
                onArrangeUndo={() => arrange('undo')}
                onPreview={setArrangePreview}
                onMove={(item, c, start) => void moveTake(item, c, start)}
                onMoveKept={(id, start) => void moveKept(id, start)}
                placing={placing}
                onPlacing={setPlacing}
                onEditingChange={setEditingLine}
                duration={project.duration}
                version={version}
              />
            </div>
          </main>
  
          {/* Voltage: black in both themes. */}
          <aside className="pane flex min-h-0 w-[400px] min-w-0 max-w-full shrink-0 flex-col overflow-x-hidden max-[960px]:h-[85dvh] max-[960px]:min-h-[60dvh] max-[960px]:w-auto" aria-label="Voltage" aria-busy={turnBusy || undefined}>
            <VoltagePane
              messages={messages}
              projectId={project.video_id}
              state={stateWord}
              busy={turnBusy || readingBusy}
              need={clarifying}
              engine={engine}
              chips={contextChips}
              cap={`Turn cap $${mayDo.turn_usd.toFixed(2)}`}
              spend={spend}
              question={clarifying ? plan?.question ?? null : null}
              onAnswer={(o, allowMore) => void clarify(o, allowMore)}
              turnCap={mayDo.turn_usd}
              onSubmit={submitComposer}
              inputRef={composerRef}
              seed={seed}
              onShowMe={showMe}
              placeholder={placeholder}
              sendLabel={sendLabel}
              working={turnBusy ? (turnStep ?? 'Working…') : null}
              suggestions={firstRead && !readingBusy ? (statements.length > 0 ? EXAMPLES : SILENT_EXAMPLES) : undefined}
              before={firstRead ? (
                <div className="flex flex-col gap-3.5" data-testid="first-read">
                  {readingBusy && !reading ? (
                    <p className="pm m-0 text-[15px]" role="status">Taking the clip in…</p>
                  ) : reading ? (
                    <p className="m-0 text-[15px] leading-relaxed">{reading.opening}</p>
                  ) : (
                    <p className="m-0 text-[15px] leading-relaxed">
                      {statements.length > 0 ? `${statements.length} ${statements.length === 1 ? 'line' : 'lines'} of speech, ${timecode(project.duration)} long. Tell me what the video should say.` : `${timecode(project.duration)} with no speech. Tell me what it should say, or ask me to look at it.`}
                    </p>
                  )}
                  {sight && (
                    <div className="flex flex-col gap-2 rounded-lg border border-pline bg-psunk p-3.5" data-testid="sight">
                      <span className="tag text-pmuted">What I saw</span>
                      <p className="m-0 text-sm leading-relaxed">{sight.setting} · {sight.mood}{sight.text_on_screen ? ` · on screen: “${sight.text_on_screen}”` : ''}</p>
                      {placeDraft === null ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm">The place: <strong>{place}</strong>{sight.place_confirmed ? '' : ` (${sight.confidence})`}</span>
                          {!sight.place_confirmed && <button type="button" className="btn volt sm" onClick={() => void confirmThePlace(sight.place_guess)}>Looks right</button>}
                          <button type="button" className="act" onClick={() => setPlaceDraft(place ?? '')}>{sight.place_confirmed ? 'Change it' : 'Correct it'}</button>
                        </div>
                      ) : (
                        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (placeDraft.trim()) void confirmThePlace(placeDraft.trim()) }}>
                          <input className="h-8 min-w-0 flex-1 rounded-md border border-pline bg-pane px-2 text-sm text-ptext outline-none focus-visible:border-volt" aria-label="The place" value={placeDraft} autoFocus onChange={(e) => setPlaceDraft(e.target.value)} />
                          <button type="submit" className="btn volt sm">Keep</button>
                          <button type="button" className="act" onClick={() => setPlaceDraft(null)}>Cancel</button>
                        </form>
                      )}
                    </div>
                  )}
                </div>
              ) : undefined}
              empty={!firstRead ? <span className="pm">Nothing said yet.</span> : undefined}
            >
              {shippedNote && (
                <div className="flex flex-col gap-2 rounded-lg border border-pline bg-psunk p-3.5" role="status" data-testid="shipped">
                  <span className="tag text-pmuted">In the video</span>
                  <span className="text-sm">{shippedNote.count} {shippedNote.count === 1 ? 'line' : 'lines'} went in on this turn{shippedNote.held > 0 ? `; ${shippedNote.held} ${shippedNote.held === 1 ? 'is' : 'are'} proposed and waiting` : ''}. Hear it in the player, or take a line out from its row.</span>
                  <div className="flex flex-wrap items-center gap-2">
                    <a className="btn volt sm" href={hrefFor({ page: 'export', projectId: project.video_id })}>Export →</a>
                    {download && <a className="act" href={download.url} download={download.filename}>Download the file</a>}
                  </div>
                </div>
              )}
              {editingLine && !turnBusy && (
                <p className="pm m-0 text-sm" role="status">You're on {clock(editingLine.start)}. Voltage stays out of the way while you write; Enter brings the line to it.</p>
              )}
            </VoltagePane>
          </aside>
        </div>
        {consentAsk && (
          <ConsentSheet who={consentAsk.who} busy={consenting} onConfirm={() => void confirmConsent()} onCancel={() => setConsentAsk(null)} />
        )}
        {firstTip && <Tip key={firstTip.id} id={firstTip.id} target={firstTip.target} />}
        <KeyboardSheet open={keysOpen} onClose={() => setKeysOpen(false)} />
        {moving && (
          <MoveDialog
            video={project}
            folders={folders}
            onClose={() => setMoving(false)}
            onFolderMade={() => void refreshProjects()}
            onMoved={(pid, pname) => { setMoving(false); setProject((p) => (p ? { ...p, project_id: pid, project_name: pname } : p)); void refreshProjects(); void refreshUsage(projectId) }}
          />
        )}
      </div>
    )
  })()
  const showChecklist = me !== null && !(me.mode === 'google' && (!me.user || signedOut)) && !project?.settings?.tutorial
  return (
    <>
      {page}
      {showChecklist && <Checklist onShowMe={showMe} />}
    </>
  )
}
