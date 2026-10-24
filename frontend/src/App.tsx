import { Fragment, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { LazyPage, LazyPart } from './lib/lazy'
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
import { shortenSentence } from './transcript/fit'
import type { LineKey } from './transcript/keys'
import { WhatVoltageMayDo } from './components/WhatVoltageMayDo'
import type { MayDo } from './components/WhatVoltageMayDo'
import { WhoSpeaks } from './components/WhoSpeaks'
import { WhatISee } from './components/WhatISee'
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
import { ResetPage } from './pages/ResetPage'
import { ExportPage } from './pages/ExportPage'
import { HelpPage } from './pages/HelpPage'
import { KnownIssuesPage } from './pages/KnownIssuesPage'
import { KeyboardSheet } from './components/KeyboardSheet'
import { FeedbackHost } from './components/FeedbackDialog'
import { StatusStrip } from './components/StatusStrip'
import { ActivityDrawer } from './components/ActivityDrawer'
import { Toaster } from './components/Toaster'
import type { TurnSummary } from './components/VoltagePane'
import { useActivity } from './jobs/useActivity'
import type { JobListener } from './jobs/useActivity'
import { aboutEta, coalesce, isActive, isRender, isVoice, stripState, turnJobs, turnSteps, turnSummary } from './jobs/model'
import type { Toast } from './jobs/model'
import { TourProvider, TourLayer, useTour } from './tour/engine'
import { guidedRun, tourById } from './tour/tours'
import type { Tour } from './tour/types'
import { OnboardingProvider, useOnboarding } from './guides/onboarding'
import { Checklist } from './guides/Checklist'
import { Tip } from './guides/Tip'
import { useReviewComments } from './review/useReviewComments'
import { useFlags } from './flags/useFlags'
import { REVIEWER_NOTE, useWorkspaceRole } from './lib/useWorkspaceRole'
import { MembersPage } from './pages/MembersPage'
import { InvitePage } from './pages/InvitePage'
import { LegalPage } from './pages/LegalPage'
import { LandingPage } from './pages/LandingPage'
import { WithdrawConsent } from './components/WithdrawConsent'
import { FeedbackProvider } from './components/Thumbs'
import { NotificationsPage } from './pages/NotificationsPage'
import { NotificationBell } from './components/NotificationBell'
import { DiscardWhy } from './components/DiscardWhy'
import { DISCARD_REASONS } from './lib/learned'
import { StageWarning } from './pages/StageWarning'
import { approvedWords } from './pages/feedWords'
import { LearnWord } from './components/LearnWord'
import { go, hrefFor, parseRoute, useRoute } from './lib/route'
import { cn } from '@/lib/utils'
import { clock } from './transcript/format'
import {
  createProject, confirmPlace, exportProject, artifactUrl, stageHold, pollJob, PollCancelled, ApiError, listVideos, listFolders, createFolder, createFolderFrom, startTutorial, getProject, deleteProject, getUsage, getSpend, listVoices, updateSpeaker, detectSpeakers, revertEdit, updateSettings, removeLine, dismissItem, easeItem, setEditRole, setCandidateRole, roleQuestion, moveCandidate, moveEdit, getArrangement, putArrangement, undoArrangement, getPlan, approvePlan, readProject, grantConsent, getMe, logout, postTurn, postAllowMore, getMessages, chipEvent, getUnderstanding, correctUnderstanding, setStyle,
  retryJob, stopJobs, getLatestRender, startRender, getJobs, listRules,
} from './api'
import type { ArrangementView, Me, PlanApproval, RoleChange, RoleQuestion } from './api'
import type { Arrangement, Placed } from './transcript/arrange'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage,
  Insert, ProjectSummary, Usage, SpendSummary, Statement, Voice, Revision,
  Plan, PlanItem, Autonomy, Reading, Piece, ProjectDetail, ApprovedEditSummary, MyVoice, ProjectFolder, ExportManifest, MixReport, Suggestion, Understanding,
  ActivityJob, PlanQuestion, RenderIncludes, RenderRecord, ProjectRule,
} from './types'
import { useMediaToken } from './lib/media'
import { askWhoIsHere, whoIsHere } from './lib/session'
import { PausedBanner } from './components/PausedBanner'
import { piecesFromInserts, renderTimeFrom, sourceTimeFrom } from './timeline/selection'

// Rehearsal item 7: behind flags that are off for the public (phases B, C, D and the admin pages); loaded on first use.
const SendForReview = lazy(() => import('./review/SendForReview').then((m) => ({ default: m.SendForReview })))
const ReviewComments = lazy(() => import('./review/Comments').then((m) => ({ default: m.ReviewComments })))
const BinPage = lazy(() => import('./pages/BinPage').then((m) => ({ default: m.BinPage })))
const TemplatesPage = lazy(() => import('./pages/Templates').then((m) => ({ default: m.TemplatesPage })))
const AdminPage = lazy(() => import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })))
const AdminEmails = lazy(() => import('./pages/AdminEmails').then((m) => ({ default: m.AdminEmails })))
const LanguageDialog = lazy(() => import('./pages/LanguageVersions').then((m) => ({ default: m.LanguageDialog })))
const SyncChip = lazy(() => import('./pages/LanguageVersions').then((m) => ({ default: m.SyncChip })))

/** What a render is (2026-10-20): its version, when it was made, and the takes it carries. */
interface RenderFacts { version?: number; at?: string; includes?: RenderIncludes; hash?: string }
const factsOf = (m: ExportManifest | RenderRecord): RenderFacts => ('edit_set_hash' in m
  ? { version: m.version, at: m.created_at, includes: m.includes, hash: m.edit_set_hash }
  : { version: m.version, at: m.created_at, includes: m.includes, hash: m.edit_hash })

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
  // Run 4 item 4c: who is here, asked first; the calls made as that person wait for it.
  useState(askWhoIsHere)
  // Launch item 2: every media address carries a signed token; re-render when it arrives or is renewed.
  useMediaToken()
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
  // 2026-10-20: a render knows its version, when it was made and the takes it carries (the player's badge and the rows read them).
  const [rendered, setRendered] = useState<{ url: string; duration: number } & RenderFacts | null>(null)
  // 20e: which render plays — the final, the original, or the preview with the proposals mixed in.
  const [view, setView] = useState<'original' | 'final' | 'proposals'>('original')
  const [preview, setPreview] = useState<{ url: string; duration: number; pieces: Piece[]; key: string; mix?: MixReport | null } & RenderFacts | null>(null)
  // 2026-10-20: what the last final render's mix did with each line.
  const [finalMix, setFinalMix] = useState<MixReport | null>(null)
  const previewing = renderPending.proposals !== null
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  // Help (2026-10-19): a goal put in the box for the guided run; a tour waiting for its video to open; the ? sheet.
  const [seed, setSeed] = useState<{ text: string; id: number } | null>(null)
  // 2026-10-20: the chips above Voltage's box, from this video (the first read, then each turn).
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  // 2026-10-20: what Voltage sees in the video (beats, style, the user's corrections).
  const [seen, setSeen] = useState<Understanding | null>(null)
  const [pendingTour, setPendingTour] = useState<Tour | null>(null)
  const [keysOpen, setKeysOpen] = useState(false)
  const [suspended, setSuspended] = useState<string | null>(null)
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
  // Phase A (projects.consistency): brief versions and project words in the editor.
  const consistency = useFlags().enabled('projects.consistency')
  // B2: language versions (Make language versions, Out of sync with master).
  const batchOn = useFlags().enabled('projects.batch')
  // C1 (projects.review): an add on an Approved video asks first ("Add anyway" runs it with the yes).
  const reviewOn = useFlags().enabled('projects.review')
  // D4: an archived project's videos are read-only; the header says so.
  const reuseOn = useFlags().enabled('projects.reuse')
  const feedbackOn = useFlags().enabled('golive.g8')
  // Rehearsal item 7: a Reviewer watches; the editor leaves out Export and asking for changes, and its lines are read-only.
  const flagsNow = useFlags()
  const role = useWorkspaceRole(flagsNow.enabled('golive.g2'), flagsNow.loading)
  const watching = role === 'reviewer'
  const safetyOn = useFlags().enabled('golive.g6')
  const [withdrew, setWithdrew] = useState(false)       // G6: keep the sentence on screen after a withdrawal
  // D2: the optional "why?" after a discard.
  const [discardWhy, setDiscardWhy] = useState<{ decisionId: number; line: string } | null>(null)
  const [stageAsk, setStageAsk] = useState<{ message: string; run: () => void; anyway?: string } | null>(null)
  const [languagesOpen, setLanguagesOpen] = useState(false)
  // A3: the project's words, for the typed-line warning and Learn a word.
  const [projectRules, setProjectRules] = useState<ProjectRule[]>([])
  const rulesProject = consistency ? project?.project_id ?? null : null
  useEffect(() => {
    if (!rulesProject) { setProjectRules([]); return }
    let live = true
    listRules(rulesProject).then((r) => { if (live) setProjectRules(r) }).catch(() => { /* no warnings shown; nothing else depends on them */ })
    return () => { live = false }
  }, [rulesProject])
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
  const [turnStep, setTurnStep] = useState<string | null>(null)
  const seenSeq = useRef(0)
  const [editingLine, setEditingLine] = useState<Statement | null>(null)
  const [playingTake, setPlayingTake] = useState<string | null>(null)
  const takeAudio = useRef<HTMLAudioElement | null>(null)
  const playingCandidate = useRef<Candidate | null>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  // Volt: the tracks panel under the scrubber, and the word-precise timeline inside it.
  const [tracksOpen, setTracksOpen] = useState(false)
  // 2026-10-20: while the editor is on screen, html and body never scroll (its panes do); elsewhere the page scrolls.
  useEffect(() => {
    document.documentElement.classList.toggle('app-locked', !!document.querySelector('[data-testid=editor-shell]'))
  })
  useEffect(() => () => document.documentElement.classList.remove('app-locked'), [])
  // One processing model (2026-10-20): the jobs, the turn and the renders every surface reads; the
  // toast (one at a time), Activity, Stop, the option just picked, and whether the picture is playing.
  const jobHandler = useRef<JobListener | null>(null)
  const [turnBusy, setTurnBusy] = useState(false)
  const activity = useActivity(project?.video_id ?? null, (job, before) => jobHandler.current?.(job, before), turnBusy)
  const [toast, setToast] = useState<Toast | null>(null)
  const pushToast = (t: Toast) => setToast((prev) => coalesce(prev, t))
  const [activityOpen, setActivityOpen] = useState(false)
  const [allJobs, setAllJobs] = useState<ActivityJob[] | null>(null)
  const [stopping, setStopping] = useState(false)
  const [picked, setPicked] = useState<{ question: PlanQuestion; option: string } | null>(null)
  const [playerPlaying, setPlayerPlaying] = useState(false)
  const swapWaiting = useRef<RenderRecord | null>(null)
  const [justReady, setJustReady] = useState(false)
  // The turn this editor started last ('pending' until the server names it), so a finished turn's steps never stand under newer words.
  const [turnIdNow, setTurnIdNow] = useState<string | null>(null)
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
    (whoIsHere() ?? getMe())
      .then(setMe)
      .catch((e) => {
        // Item 10: a suspended account is signed out and told why, on the sign-in page.
        if (e instanceof ApiError && e.status === 403 && (e.body as { code?: string } | null)?.code === 'suspended') {
          setSuspended(e.message)
          void logout().catch(() => undefined)
          setMe({ mode: 'google', user: null })
          return
        }
        setMe({ mode: 'off', user: null })   // an older server: open as before
      })
  }, [])

  // G2: an invite opened before signing in comes back once signed in.
  useEffect(() => {
    // Any sign-in (Google or an email and password), not only Google: rehearsal found
    // an invite opened before signing up was lost once the account was confirmed.
    if (!me || me.mode === 'off' || !me.user) return
    let token: string | null = null
    try { token = sessionStorage.getItem('voltage-invite'); sessionStorage.removeItem('voltage-invite') } catch { /* nothing waiting */ }
    if (token) go({ page: 'invite', token })
  }, [me])

  // A 401 anywhere means the session ended: back to the door.
  useEffect(() => {
    if (me?.mode !== 'off' && me && error === 'Sign in to continue.') setSignedOut(true)
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
    setSuggestions([])
    setSeen(null)
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
  // C2 (projects.review): the client's comments, as scrubber marks and a list under the transcript.
  const review = useReviewComments(projectId, reviewOn)
  const [reviewOpen, setReviewOpen] = useState(false)
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
    getUnderstanding(projectId).then((u) => { if (live) setSeen(u) }).catch(() => {})
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
      .then((r) => { setReading(r); if (r.suggestions?.length) setSuggestions(r.suggestions); void getUnderstanding(projectId).then(setSeen).catch(() => {}) })
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
    setSuggestions(loaded.suggestions ?? [])
    // The thread's high-water mark belongs to this project: a fresh upload after
    // another project starts at zero, or its first replies would be skipped.
    seenSeq.current = Math.max(0, ...((loaded as Partial<ProjectDetail>).messages ?? []).map((m) => m.seq ?? 0))
    // UX-7c: one workspace. A fresh project is read on arrival (a clip with
    // no speech is looked at); one with a plan or edits opens as it was.
    wantReading.current = !loaded.plan && !edited
    opening.current = loaded.video_id
    // Rehearsal item 7: an export page opened directly (a link, a reload) stays on the export page.
    const here = parseRoute(window.location.hash)
    if (!(here.page === 'export' && here.projectId === loaded.video_id)) go({ page: 'editor', projectId: loaded.video_id })
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
      setError('Could not load the sample video.')
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

  const confirmConsent = async (livenessId: string | null = null) => {
    if (!projectId || !consentAsk) return
    setConsenting(true)
    try {
      const r = await grantConsent(projectId, livenessId)
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
  const moveKept = async (editId: string, start: number, confirmStage = false) => {
    if (!projectId) return
    setError(null)
    try {
      const r = await moveEdit(projectId, editId, confirmStage ? { start, confirm_stage: true } : { start })
      if (confirmStage) leftApproved()
      const { selection: at, new_text: text, mix = 'replace' } = r.candidate.plan
      setApproved((a) => a.map((rev) => (
        rev.edit_id === editId ? { ...rev, edit_id: r.edit_id, start: at.start, end: at.end, text, mix, partner: rev.partner ?? null }
        : rev.partner === editId ? { ...rev, partner: r.edit_id } : rev
      )))
      setDownload(null)
      if (await runExport()) setView('final')
    } catch (e) {
      if (stageHeld(e, () => void moveKept(editId, start, true))) return
      setError(e instanceof ApiError ? e.message : 'Could not move the line.')
    }
  }

  /** C1: an add on an Approved video waits for "Add anyway"; true when it was held. */
  const heldByStage = (run: () => void): boolean => {
    if (!reviewOn || project?.stage !== 'approved') return false
    setStageAsk({ message: approvedWords([]), run })
    return true
  }
  /** C1: the server held the add (the stage moved since the video was read): the same warning. */
  const stageHeld = (e: unknown, run: () => void): boolean => {
    const hold = stageHold(e)
    if (!hold) return false
    setProject((p) => (p ? { ...p, stage: 'approved' } : p))
    setStageAsk({ message: hold.message, run, anyway: hold.options[0] })
    return true
  }
  /** C1: an edit landed, so an Approved video is a Draft again (the server moved it in the same step). */
  const leftApproved = () => setProject((p) => (p && p.stage === 'approved' ? { ...p, stage: 'draft' } : p))

  /** Add it (20e): the proposal under a line goes into the video — its plan
   *  item is approved and rendered. A take that failed its sound check is
   *  added on the user's word. */
  const addItem = async (item: PlanItem, confirmStage = false) => {
    if (!projectId || !plan) return
    setError(null)
    if (!confirmStage && heldByStage(() => void addItem(item, true))) return
    try {
      const passed = item.candidate?.continuity.passed ?? true
      const seq = beginRender('final')
      let result: PlanApproval | null = null
      try {
        result = await approvePlan(projectId, plan.plan_id, { items: [item.item_id], ...(passed ? {} : { override: true }), ...(confirmStage ? { confirm_stage: true } : {}) })
        takeInApproval(result, seq)
        if (result.approved.length > 0) leftApproved()
      } finally {
        endRender('final', seq, result?.export ?? null)
      }
      setPreview(null)
    } catch (e) {
      if (stageHeld(e, () => void addItem(item, true))) return
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
      const { decision_id: decisionId, ...next } = await dismissItem(projectId, plan.plan_id, item.item_id)
      setPlan(next)
      setPreview(null)
      // D2: in a project, one optional "why?" for what Voltage learns there.
      if (reuseOn && project?.project_id && decisionId != null) setDiscardWhy({ decisionId, line: `the line at ${clock(item.selection.start)}` })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not discard that line.')
    }
  }
  /** p61: a line that ran long takes its take already voiced, the picture easing; nothing is paid. */
  const easeLine = async (item: PlanItem) => {
    if (!projectId || !plan) return
    setError(null)
    try {
      setPlan(await easeItem(projectId, plan.plan_id, item.item_id))
      setPreview(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not ease that line in.')
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
  const arrange = async (next: Arrangement | 'undo', confirmStage = false) => {
    if (!projectId) return
    setError(null)
    try {
      setArranged(next === 'undo' ? await undoArrangement(projectId) : await putArrangement(projectId, next, confirmStage))
      if (confirmStage) leftApproved()
      setDownload(null)
      if (await runExport()) setView('final')
    } catch (e) {
      if (next !== 'undo' && stageHeld(e, () => void arrange(next, true))) return
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
    const option = answer ?? plan.question.guess ?? plan.question.options[0]
    // The card stays where it was, its options off and the pick marked; your words echo at once below it.
    setPicked({ question: plan.question, option })
    return takeTurn(option, false, allowMore && !!plan.question.turn_cap)
  }

  /** The box is for the whole video: a goal, a change to the plan, an answer.
   *  With words selected on the Precise timeline, the sentence names the time. */
  const submitComposer = (text: string) => { setPicked(null); void takeTurn(selection && precise ? `At ${clock(selection.start)}: ${text}` : text) }

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
      if (!allowMore) setTurnIdNow('pending')
      const job = allowMore ? await postAllowMore(projectId) : await postTurn(projectId, text)
      if (!allowMore) setTurnIdNow(job.job_id)
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
    edit_id: e.edit_id, start: e.selection.start, end: e.selection.end, text: e.new_text, mix: e.mix, partner: e.partner ?? null, role: e.role ?? 'voice', offset_db: e.offset_db ?? null,
    speaker: e.speaker ?? null, voice_profile_id: e.voice_profile_id ?? null,
  })
  /** The plan item just approved, as a revision. */
  const itemRevision = (i: PlanItem): Revision => ({
    edit_id: i.edit_id!, start: i.candidate?.plan.selection.start ?? i.selection.start,
    end: i.candidate?.plan.selection.end ?? i.selection.end, text: i.new_text, mix: i.mix, role: i.candidate?.plan.role ?? 'voice', offset_db: i.candidate?.plan.offset_db ?? null,
    speaker: i.speaker ?? null, voice_profile_id: i.candidate?.plan.voice_profile_id ?? null,
  })

  /** B2: the sync turn on this language version ended: its lines and whether it is in step, read again. */
  const settleSync = async (id: string) => {
    const latest = await getProject(id).catch(() => null)
    if (!latest) return
    setProject((p) => (p && p.video_id === id ? { ...p, out_of_sync: latest.out_of_sync } : p))
    await syncEdits()
  }

  /** 20g: after a turn, the edits as the server has them — Voltage may have undone or releveled a line — so the transcript never shows a stale row. */
  const syncEdits = async (): Promise<{ changed: boolean; render: { download: { url: string; filename: string }; duration: number } | null }> => {
    if (!projectId) return { changed: false, render: null }
    const latest = await getProject(projectId).catch(() => null)
    if (!latest) return { changed: false, render: null }
    // p60: the items too, not only the edits, so the rows, the header's counts and Voltage's words come from one record.
    if (latest.plan) setPlan(latest.plan)
    if (latest.suggestions) setSuggestions(latest.suggestions)
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

  /** 2026-10-20: a line's role in the mix, or its fine-tune, nothing voiced again. The
   *  only speech in its span comes back as a question for the row to ask. */
  const changeRole = async (target: { editId?: string; candidate?: Candidate; item?: PlanItem }, change: RoleChange): Promise<RoleQuestion | null> => {
    if (!projectId) return null
    setError(null)
    try {
      if (target.editId) {
        const r = await setEditRole(projectId, target.editId, change)
        if (change.confirm_stage) leftApproved()
        setApproved((all) => all.map((rev) => (rev.edit_id === target.editId
          ? { ...rev, edit_id: r.edit_id, role: r.candidate.plan.role ?? 'voice', offset_db: r.candidate.plan.offset_db ?? null } : rev)))
        setPreview(null)
        if (await runExport()) setView('final')
      } else if (target.candidate && target.item) {
        const c = await setCandidateRole(projectId, target.candidate.candidate_id, change)
        const id = target.item.item_id
        setPlan((p) => (p ? { ...p, items: p.items.map((i) => (i.item_id === id ? { ...i, candidate: c } : i)) } : p))
        setPreview(null)
      }
      return null
    } catch (e) {
      const asked = roleQuestion(e)
      if (asked) return asked
      if (stageHeld(e, () => void changeRole(target, { ...change, confirm_stage: true }))) return null
      setError(e instanceof ApiError ? e.message : 'Could not change how the line is mixed.')
      return null
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
    setFinalMix(result.export.mix ?? null)
    const stem = (project?.filename ?? 'video').replace(/\.[^.]+$/, '')
    const url = artifactUrl(projectId, result.export.render.sha256)
    const download = { url, filename: `${stem}-edited.mp4` }
    setDownload(download)
    setRendered({ url, duration: result.export.render.duration, ...factsOf(result.export) })
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
  const approveAll = async (items: PlanItem[], confirmStage = false) => {
    if (!projectId || !plan) return
    setError(null)
    if (!confirmStage && heldByStage(() => void approveAll(items, true))) return
    const seq = beginRender('final')
    let manifest: ExportManifest | null = null
    try {
      const result = await approvePlan(projectId, plan.plan_id, {
        items: items.map((i) => i.item_id), override: items.some((i) => !(i.candidate?.continuity.passed ?? true)),
        ...(confirmStage ? { confirm_stage: true } : {}),
      })
      manifest = result.export ?? null
      takeInApproval(result, seq)
      if (result.approved.length > 0) leftApproved()
      setPreview(null)
      if (result.skipped.length > 0) {
        setError(`${result.skipped.length} ${result.skipped.length === 1 ? 'line was' : 'lines were'} not added. Hear them, then Add it one by one or ask for another take.`)
      }
    } catch (e) {
      if (stageHeld(e, () => void approveAll(items, true))) return
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

  // A2: a link from the project check opens the editor at a time (#v/p12@3.5), once the video is open.
  const seekedFor = useRef<string | null>(null)
  const routeT = route.page === 'editor' ? route.t ?? null : null
  useEffect(() => {
    if (routeT === null || loading || !project || route.page !== 'editor' || project.video_id !== route.projectId) return
    const key = `${route.projectId}@${routeT}`
    if (seekedFor.current === key) return
    seekedFor.current = key
    const time = view === 'final' && rendered !== null ? renderTimeFrom(routeT, pieces) : routeT
    setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 }))
    setCurrentTime(time)
  }, [routeT, loading, project, route, view, rendered, pieces])

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
      setPreview({ url, duration: manifest.render.duration, key, mix: manifest.mix ?? null,
        pieces: manifest.pieces ?? piecesFromInserts(manifest.inserts ?? [], project?.duration ?? 0), ...factsOf(manifest) })
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
    // Where the renders stand now (the version, nothing stale): read once the editor's own render is back.
    if (latest) void activity.refresh()
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
      setFinalMix(manifest.mix ?? null)
      const stem = (filename ?? 'video').replace(/\.[^.]+$/, '')
      const url = artifactUrl(id, manifest.render.sha256)
      const download = { url, filename: `${stem}-edited.mp4` }
      setDownload(download)
      setRendered({ url, duration: manifest.render.duration, ...factsOf(manifest) })
      return { download, duration: manifest.render.duration }
    } catch {
      if (isLatest('final', seq)) setError('Export failed.')
      return null
    } finally {
      endRender('final', seq, manifest)
    }
  }

  // ── One processing model (2026-10-20) ──────────────────────────────────────

  /** The key a proposals render is for: the ready takes, in order. */
  const readyKey = (p: Plan | null) => (p?.items ?? []).filter((i) => i.kind === 'planned' && i.status === 'ready').map((i) => i.candidate?.candidate_id ?? i.item_id).join(',')
  /** The pieces of what the player plays now, to carry the playhead into another file. */
  const piecesNow = () => (view === 'final' && rendered ? pieces : view === 'proposals' && preview ? preview.pieces : [])
  const versionNow = view === 'final' ? rendered?.version ?? null : view === 'proposals' ? preview?.version ?? null : null

  /** A finished render into the player: its file, its pieces, its version. With `switchTo` (or when its mode is
   *  playing) the player moves to it at the same moment of the source, mapped through the pieces. */
  const adopt = (rec: RenderRecord, switchTo: boolean) => {
    if (!projectId || !rec.manifest) return
    const m = rec.manifest
    const url = artifactUrl(projectId, rec.render.sha256)
    const pcs = m.pieces ?? piecesFromInserts(m.inserts ?? [], project?.duration ?? 0)
    const now = piecesNow()
    const source = now.length ? sourceTimeFrom(currentTime, now) : currentTime
    if (rec.mode === 'final') {
      setSegments(m.segments)
      setInserts(m.inserts ?? [])
      setPieces(pcs)
      setFinalMix(m.mix ?? null)
      setDownload({ url, filename: `${(project?.filename ?? 'video').replace(/\.[^.]+$/, '')}-edited.mp4` })
      setRendered({ url, duration: rec.render.duration, ...factsOf(rec) })
    } else {
      setPreview({ url, duration: rec.render.duration, key: readyKey(plan), mix: m.mix ?? null, pieces: pcs, ...factsOf(rec) })
    }
    if (switchTo || view === rec.mode) {
      setCarry((c) => ({ time: pcs.length ? renderTimeFrom(source, pcs) : source, id: (c?.id ?? 0) + 1 }))
      setView(rec.mode)
      setJustReady(true)
    }
  }

  /** A render finished on the server: swapped in at the playhead when the picture is paused; while it plays,
   *  a toast asks first ("v5 ready. Switch now?"), so nothing changes under a word. A render of another mode
   *  is kept for when that mode is played, unless a turn made it (then it is what the turn asks you to hear). */
  const offerRender = async (job: ActivityJob) => {
    const mode = job.detail?.mode
    if (!projectId || !mode) return
    const state = await getLatestRender(projectId, mode).catch(() => null)
    const rec = state?.latest
    if (!rec?.manifest) return
    const have = mode === 'final' ? rendered?.version : preview?.version
    if (have != null && rec.version <= have) return
    if (view !== mode && !job.turn_id) { adopt(rec, false); return }
    if (playerPlaying) {
      swapWaiting.current = rec
      pushToast({ id: `swap-${rec.render_id}`, tone: 'ok', text: `v${rec.version} ready. Switch now?`, action: { label: 'Switch now', key: 'swap' } })
    } else {
      adopt(rec, true)
    }
  }

  // What a job's change means for the toasts, the rows and the player. A job read on open is not news.
  jobHandler.current = (job, before) => {
    if (isVoice(job) && !isActive(job) && projectId && plan) getPlan(projectId, plan.plan_id).then(setPlan).catch(() => {})
    if (!before) return
    if (job.status === 'failed' && before.status !== 'failed') {
      const what = isVoice(job) ? 'A line failed' : isRender(job) ? 'A render failed' : 'A job failed'
      pushToast({ id: job.job_id, tone: 'fail', text: `${what}: ${job.error_text ?? 'no reason was given'}`, action: { label: 'Activity', key: 'activity' } })
    }
    if (isVoice(job) && job.status === 'done' && before.status !== 'done') pushToast({ id: job.job_id, tone: 'ok', text: '1 line ready' })
    if (isRender(job) && job.status === 'done' && before.status !== 'done') void offerRender(job)
  }

  const onToastAction = (t: Toast) => {
    setToast(null)
    if (t.action?.key === 'swap' && swapWaiting.current) { adopt(swapWaiting.current, true); swapWaiting.current = null }
    if (t.action?.key === 'activity') openActivity()
  }

  const openActivity = () => {
    setActivityOpen(true)
    if (projectId) getJobs(projectId).then((r) => setAllJobs(r.jobs)).catch(() => setAllJobs(null))
  }

  /** Stop: queued jobs are cancelled, the running one finishes, the turn ends after its step. */
  const stopAll = async () => {
    if (!projectId) return
    setStopping(true)
    try {
      const r = await stopJobs(projectId)
      await activity.refresh()
      pushToast({ id: 'stop', tone: 'ok', text: r.cancelled ? `Stopping. ${r.cancelled} queued ${r.cancelled === 1 ? 'job' : 'jobs'} cancelled; the one running finishes.` : 'Stopping after the step that is running.' })
    } catch (e) {
      setStopping(false)
      setError(e instanceof ApiError ? e.message : 'Could not stop that.')
    }
  }

  /** Retry a failed job through the same flow: the same words and voice, or the same render. */
  const retry = async (job: ActivityJob) => {
    if (!projectId) return
    try {
      const next = await retryJob(projectId, job.job_id)
      activity.take(next)
      setAllJobs((all) => (all ? [next, ...all.filter((j) => j.job_id !== next.job_id)] : all))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not retry that.')
    }
  }

  /** Render now: the edits as they are, in the background; the player takes it when it is ready. */
  const renderNow = async (mode: 'final' | 'proposals') => {
    if (!projectId) return
    try {
      activity.take(await startRender(projectId, mode))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the render.')
    }
  }

  /** The lines a turn voiced (item ids), from its finished voice jobs. */
  const turnLines = (turnId: string) => [...new Set(turnJobs(activity.jobs, turnId).filter((j) => isVoice(j) && j.status === 'done').flatMap((j) => j.line_ids))]

  /** Hear changes: from just before the first line the turn changed, in the version that has it. */
  const hearTurn = (turnId: string, mode: 'final' | 'proposals' | null) => {
    const ids = new Set(turnLines(turnId))
    const starts = (plan?.items ?? []).filter((i) => ids.has(i.item_id)).map((i) => i.candidate?.plan.selection.start ?? i.selection.start)
    if (!starts.length) return
    const at = Math.max(0, Math.min(...starts) - 0.5)
    const target = mode && (mode === 'final' ? rendered : preview) ? mode : view
    const pcs = target === 'final' && rendered ? pieces : target === 'proposals' && preview ? preview.pieces : []
    const time = pcs.length ? renderTimeFrom(at, pcs) : at
    if (target !== view) {
      setCarry((c) => ({ time, id: (c?.id ?? 0) + 1 }))
      setView(target)
      window.setTimeout(() => setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1, play: true })), 250)
    } else {
      setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1, play: true }))
    }
    setCurrentTime(time)
  }

  /** Undo all: every line the turn voiced leaves the video and the plan (asked once on the card first). */
  const undoTurn = async (turnId: string) => {
    if (!projectId || !plan) return
    const ids = new Set(turnLines(turnId))
    const fresh = await getPlan(projectId, plan.plan_id).catch(() => plan)
    for (const it of fresh.items) {
      if (!ids.has(it.item_id)) continue
      if (it.status === 'approved' && it.edit_id) await revertEdit(projectId, it.edit_id).catch(() => {})
      if (['approved', 'ready', 'failed', 'planned'].includes(it.status)) await dismissItem(projectId, fresh.plan_id, it.item_id).catch(() => {})
    }
    setPlan(await getPlan(projectId, plan.plan_id).catch(() => fresh))
    await syncEdits()
    pushToast({ id: `undo-${turnId}`, tone: 'ok', text: `Undid ${ids.size} ${ids.size === 1 ? 'line' : 'lines'}.` })
  }

  // The turn finished: one toast with its summary.
  const lastTurn = useRef<{ id: string; status: string } | null>(null)
  useEffect(() => {
    const t = activity.turn
    const prev = lastTurn.current
    lastTurn.current = t ? { id: t.turn_id, status: t.status } : null
    if (!t || !prev || prev.id !== t.turn_id) return
    if ((prev.status === 'running' || prev.status === 'stopping') && (t.status === 'done' || t.status === 'failed')) {
      // The version is the summary's to name (it knows when the new one is playing); the toast says what finished.
      pushToast({ id: `turn-${t.turn_id}`, tone: t.status === 'failed' ? 'fail' : 'ok', text: turnSummary(t, activity.jobs, null, false) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activity.turn])

  // The tab: a dot while anything runs, "Ready" for a moment when it is all done.
  const anyBusy = activity.jobs.some(isActive) || activity.turn?.status === 'running' || activity.turn?.status === 'stopping' || turnBusy
  const baseTitle = useRef(typeof document !== 'undefined' ? document.title : 'Voltage')
  const wasBusy = useRef(false)
  useEffect(() => {
    const base = baseTitle.current
    if (anyBusy) { document.title = `● ${base}`; wasBusy.current = true; return }
    if (!wasBusy.current) return
    wasBusy.current = false
    setStopping(false)
    document.title = `Ready · ${base}`
    const t = window.setTimeout(() => { document.title = base }, 4000)
    return () => window.clearTimeout(t)
  }, [anyBusy])
  useEffect(() => () => { document.title = baseTitle.current }, [])
  useEffect(() => {
    if (!justReady) return
    const t = window.setTimeout(() => setJustReady(false), 6000)
    return () => window.clearTimeout(t)
  }, [justReady])

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
    if (route.page === 'legal') return <LegalPage doc={route.doc} />     // G6: readable without an account
    if (route.page === 'welcome') return <LandingPage />
    if (route.page === 'invite' && me.mode !== 'off' && (!me.user || signedOut)) {
      // G2: sign in first, then come back to the invite.
      try { sessionStorage.setItem('voltage-invite', route.token) } catch { /* the link can be opened again */ }
    }
    if (me.mode !== 'off' && (!me.user || signedOut)) {
      // Launch item 5: a password reset link works signed out.
      if (route.page === 'reset') return <ResetPage token={route.token} onDone={() => window.location.reload()} />
      // Launch item 8: the start (`#`, `#home`) is the landing page for someone not signed in.
      if (route.page === 'projects' && !signedOut) return <LandingPage />
      return <LoginPage onSignedIn={() => { if (route.page === 'login') window.location.hash = '#home'; window.location.reload() }} error={suspended ?? (signedOut ? 'Your session ended. Sign in again to continue.' : route.page === 'login' ? route.error ?? null : null)} />
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
          onNewFolder={async (name, templateId) => { const made = templateId ? await createFolderFrom(name, templateId) : await createFolder(name); await refreshProjects(); return made }}
          onFolderMade={() => void refreshProjects()}
          onMoved={() => void refreshProjects()}
          onSampleMade={() => void refreshProjects()}
          banner={role !== null && !watching && onboarding.loaded && !onboarding.onboarding.tour.finished && !onboarding.onboarding.tour.skipped ? (
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
    if (route.page === 'knownIssues') return <KnownIssuesPage me={me} />
    if (route.page === 'voices') return <VoicesPage me={me} />
    if (route.page === 'usage') return <UsagePage me={me} scope={route.scope ?? null} />
    if (route.page === 'settings') return <SettingsPage me={me} onSignedOut={signedOutNow} />
    if (route.page === 'billing') return <BillingPage me={me} />
    if (route.page === 'bin') return <LazyPage><BinPage me={me} onRestored={() => void refreshProjects()} /></LazyPage>
    if (route.page === 'members') return <MembersPage me={me} />
    if (route.page === 'notifications') return <NotificationsPage me={me} />
    if (route.page === 'admin') return <LazyPage><AdminPage me={me} /></LazyPage>
    if (route.page === 'adminEmails') return <LazyPage><AdminEmails me={me} /></LazyPage>
    if (route.page === 'invite') return <InvitePage token={route.token} />
    if (route.page === 'templates') return <LazyPage><TemplatesPage me={me} onMade={() => void refreshProjects()} /></LazyPage>
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
    // A preview made on the server (a turn's render) is ready when it carries exactly the takes waiting.
    const carriesReady = (inc?: RenderIncludes) => !!inc && inc.item_ids.length === readyItems.length
      && readyItems.every((i) => !!i.candidate && inc.candidate_ids.includes(i.candidate.candidate_id))
    const previewReady = preview !== null && (preview.key === previewKey || carriesReady(preview.includes))
    const shown = view === 'final' && rendered ? { url: rendered.url, duration: rendered.duration, pieces }
      : view === 'proposals' && previewReady ? { url: preview!.url, duration: preview!.duration, pieces: preview!.pieces }
      : null
    // A question picked from is answered: nothing waits on you while that turn runs.
    const clarifying = plan?.status === 'clarifying' && !turnBusy
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
      ...(seen?.beats ?? []).filter((b) => b.kind !== 'cut').map((b) => ({ at: toRender(b.at), tone: 'beat' as const, label: `Beat: ${b.label}` })),
      // C2: a client's open comment, at its time in the version they watched.
      ...(review.comments ?? []).filter((c) => c.status === 'open').map((c) => ({ at: c.at_s, tone: 'comment' as const, label: `Comment from ${c.author_name}: ${c.text}` })),
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
    // 2026-10-20: the three modes are always there; one with nothing in it yet is off and says why.
    const views = [
      ['final', 'Edited', changes > 0, 'Nothing is added yet'] as const,
      ['proposals', 'With proposals', readyItems.length > 0, 'No proposals are waiting'] as const,
      ['original', 'As shot', true, ''] as const,
    ]
    // Player truth: the badge names the mode and the version playing.
    const playingRec = view === 'final' && rendered ? rendered : view === 'proposals' && previewReady ? preview : null
    const MODE_WORD = { final: 'Edited', proposals: 'With proposals', original: 'As shot' } as const
    const badge = view === 'original' ? 'Playing original'
      : shown ? `Playing ${playingRec?.version ? `v${playingRec.version} · ` : ''}${MODE_WORD[view]}`
      : `Playing original · ${MODE_WORD[view]} not ready`
    // What is rendering for the mode playing, or what is not in it yet.
    const modeNow = view === 'original' ? null : view
    // The render on its way: one for the mode playing, or the one a turn is making (it is what will swap in).
    const renderJob = activity.jobs.find((j) => isRender(j) && isActive(j) && modeNow !== null && (j.detail?.mode ?? 'final') === modeNow)
      ?? activity.jobs.find((j) => isRender(j) && isActive(j) && !!j.turn_id) ?? null
    const inProgress = modeNow ? activity.renders[modeNow]?.in_progress ?? null : null
    const renderingVersion = renderJob?.detail?.version ?? inProgress?.version ?? null
    const renderingEta = aboutEta(renderJob?.eta_s ?? inProgress?.eta_s ?? null)
    const localRender = modeNow ? renderPending[modeNow] !== null : false
    const modeState = modeNow ? activity.renders[modeNow] : null
    const stale = !!modeState?.stale && !renderJob && !inProgress && !localRender
      && (modeNow === 'final' ? changes > 0 : readyItems.length > 0)
      && !(playingRec?.hash && playingRec.hash === modeState.current_hash)
    const renderNote = renderJob || inProgress || localRender ? (
      <span className="tag" role="status" data-testid="render-note">{renderingVersion ? `v${renderingVersion} rendering…` : 'Rendering…'}{renderingEta ? ` ${renderingEta}` : ''}</span>
    ) : stale && modeNow ? (
      <>
        <span className="tag text-needs" role="status" data-testid="render-note">Changes not in preview yet</span>
        <button type="button" className="btn sm" onClick={() => void renderNow(modeNow)}>Render now</button>
      </>
    ) : null
    // The rows' one chip reads what the video playing carries (the edited render while As shot plays) and what is rendering.
    const videoRender = view === 'proposals' ? (previewReady ? preview : null) : rendered
    const perChar = (() => {
      const xs = activity.jobs.filter((j) => isVoice(j) && j.status === 'done' && j.started_at && j.finished_at && j.detail?.chars)
        .map((j) => (Date.parse(j.finished_at!) - Date.parse(j.started_at!)) / 1000 / j.detail!.chars!).filter((x) => x > 0).sort((a, b) => a - b)
      return xs.length ? xs[Math.floor(xs.length / 2)] : null
    })()
    const rowActivity = {
      jobs: activity.jobs,
      video: videoRender?.includes ?? null,
      videoUnknown: !videoRender?.includes,
      rendering: renderJob?.detail?.includes ?? inProgress?.includes ?? activity.jobs.find((j) => isRender(j) && isActive(j))?.detail?.includes ?? null,
      onRetryJob: retry,
      etaFor: (chars: number) => (perChar ? perChar * chars : null),
    }
    // The status strip, the chat's step list and the turn's summary, all from the same jobs.
    const localTurn = turnBusy ? { turn_id: 'local', status: 'running' as const, step: turnStep ?? 'Thinking', started_at: '', finished_at: null } : null
    const ourTurn = activity.turn && (turnIdNow === null || turnIdNow === activity.turn.turn_id) ? activity.turn : null
    const strip = stripState({
      jobs: activity.jobs, turn: ourTurn ?? localTurn,
      playing: playingRec?.version ? { version: playingRec.version, created_at: playingRec.at ?? '' } : null,
      stale, justReady,
    })
    const canStop = activity.jobs.some(isActive) || ourTurn?.status === 'running' || turnBusy
    const steps = ourTurn ? turnSteps(ourTurn, activity.jobs) : []
    const turnDone = ourTurn && (ourTurn.status === 'done' || ourTurn.status === 'failed')
    const summary: TurnSummary | null = turnDone && !clarifying && steps.some((st) => st.key === 'voice' || st.key === 'render') ? {
      text: turnSummary(ourTurn, activity.jobs, versionNow),
      lines: turnLines(ourTurn.turn_id).length,
      onHear: () => hearTurn(ourTurn.turn_id, ourTurn.render?.mode ?? null),
      onUndo: () => undoTurn(ourTurn.turn_id),
    } : null
    const liveQuestion = clarifying ? plan?.question ?? null : plan?.question?.resolved?.by === 'editor' ? plan.question : null
    const question = picked && liveQuestion && liveQuestion.text === picked.question.text ? null : liveQuestion
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
    const scanning = turnBusy ? strip.text : readingBusy ? 'Voltage is reading the video' : null
    const isTutorial = !!project.settings?.tutorial
    const tipCandidates: { id: string; target: string; when: boolean }[] = [
      { id: 'first-review-comment', target: 'scrubber', when: reviewOn && (review.comments ?? []).some((c) => c.status === 'open') },
      { id: 'first-failed-take', target: 'transcript-row', when: planItems.some((i) => i.status === 'failed') },
      { id: 'first-word-rule', target: 'transcript-row', when: consistency && planItems.some((i) => !!i.word_rule?.breaks?.length) },
      { id: 'first-ceiling', target: 'spend', when: !!error && /ceiling/i.test(error) },
      // G3: paid steps paused because the credits are used up.
      { id: 'first-credits', target: 'spend', when: !!error && /credits are used up/i.test(error) },
      { id: 'first-question', target: 'question', when: !!clarifying && !plan?.question?.gate },
      { id: 'first-voice-design', target: 'composer', when: messages.some((m) => m.kind === 'previews') },
      { id: 'first-undo-after-export', target: 'export', when: undoneAfterExport },
      { id: 'first-background', target: 'transcript-row', when: approved.some((r) => r.role === 'bed') },
      { id: 'first-just-do-it', target: 'autonomy', when: autonomy === 'draft' },
      { id: 'first-silent', target: 'composer', when: !isTutorial && firstRead && statements.length === 0 },
      { id: 'first-upload', target: 'composer', when: !isTutorial && firstRead && statements.length > 0 && !readingBusy },
      // G8: thumbs on a take, once a take is there to rate.
      { id: 'first-thumbs', target: 'transcript-row', when: feedbackOn && planItems.some((i) => i.status === 'ready' && !!i.candidate) },
      // G6 (9e): the Withdraw consent now row, once consent is on record.
      { id: 'first-withdraw-consent', target: 'withdraw-consent', when: safetyOn && !!project.consent_granted_at && !consentAsk },
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
      <FeedbackProvider videoId={project.video_id}>
      <div className="grid h-dvh grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden bg-background text-foreground max-[960px]:block max-[960px]:h-auto max-[960px]:min-h-dvh max-[960px]:overflow-visible" data-testid="editor-shell">
        <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to the transcript</a>
        {/* Volt: the editor's header — the wordmark, the file, the play switch, the autonomy, the spend, Export, the account. */}
        <PausedBanner floating />
        <header className="z-30 flex min-h-[62px] min-w-0 flex-wrap max-[960px]:sticky max-[960px]:top-0 items-center gap-x-4 gap-y-2 border-b-[1.5px] border-foreground bg-card px-4 py-2 sm:px-6 max-[1600px]:gap-x-3 lg:[&>*:not(h1)]:shrink-0" data-testid="editor-header">
          <Wordmark />
          <span className="text-faint max-[1600px]:hidden" aria-hidden="true">/</span>
          {/* Folders: the project the video is in, with its menu; or a dashed "No project" that opens the move dialog. */}
          <div className="relative" data-crumb>
            {project.project_id ? (
              <button type="button" className="inline-flex h-[34px] items-center gap-2 rounded-lg border-[1.5px] border-line2 bg-card px-2.5 font-semibold hover:border-foreground" aria-haspopup="menu" aria-expanded={crumbMenu} onClick={() => setCrumbMenu((m) => !m)} data-testid="crumb">
                <span aria-hidden="true" className="h-3 w-4 shrink-0 rounded-[3px] border-[1.5px] border-ink bg-volt" /><span className="max-w-[28ch] truncate max-[1600px]:max-w-[14ch]" title={project.project_name ?? undefined}>{project.project_name ?? 'Project'}</span><span aria-hidden="true" className="text-xs">▾</span>
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
                {reviewOn && <button type="button" role="menuitem" className="act justify-start gap-2.5" onClick={() => { setCrumbMenu(false); setReviewOpen(true) }} data-testid="menu-review"><span aria-hidden="true" className="w-4 text-center">✓</span>Send for review…</button>}
                {batchOn && !project.master_id && <button type="button" role="menuitem" className="act justify-start gap-2.5" onClick={() => { setCrumbMenu(false); setLanguagesOpen(true) }} data-testid="menu-languages"><span aria-hidden="true" className="w-4 text-center">⇄</span>Make language versions…</button>}
                <div className="mx-1 mt-1.5 mb-1 flex flex-col gap-1 rounded-lg bg-sunk p-2.5">
                  <span className="tag text-faint">Brief Voltage is using</span>
                  <span className="line-clamp-3 text-[13px]">{folderOf?.brief?.trim() ? folderOf.brief : 'No brief yet.'}</span>
                  <a className="tag text-foreground no-underline" href={hrefFor({ page: 'folder', projectId: project.project_id })} onClick={() => setCrumbMenu(false)}>Edit brief →</a>
                </div>
              </div>
            )}
          </div>
          {/* The status chips (archived, brief changed, language version, out of sync) take a row of their own under the header's row, so the file name, Export, the bell and the account always fit. */}
          {(reuseOn && project.project_id && project.project_archived) || (consistency && project.project_id && project.brief_changed) || (batchOn && project.master_id) ? (
          <div className="order-last flex min-w-0 basis-full flex-wrap items-center gap-2" data-testid="header-chips">
          {reuseOn && project.project_id && project.project_archived && (
            <a className="stamp quiet no-underline" href={hrefFor({ page: 'folder', projectId: project.project_id })} title="This project is archived. Unarchive it to make changes." data-testid="archived">Archived</a>
          )}
          {/* A1: the project's brief moved on since this video's last shipped edit. */}
          {consistency && project.project_id && project.brief_changed && (
            <a className="stamp need no-underline" href={hrefFor({ page: 'folder', projectId: project.project_id })} title={`Made with brief v${project.made_with_brief ?? 0}; ${project.project_name ?? 'the project'} is on v${project.brief_version}. Open the project to bring it up to date.`} data-testid="brief-changed">Brief changed</a>
          )}
          {/* B2: a language version names its master, and says when the master moved on. */}
          {batchOn && project.master_id && (
            <a className="stamp in whitespace-nowrap no-underline" href={hrefFor({ page: 'editor', projectId: project.master_id })} title={`The ${project.language_label} version of ${project.master_filename ?? 'its master'}. Open the master.`} data-testid="language-of">{project.language_label} · of {project.master_filename ?? 'master'}</a>
          )}
          {batchOn && project.master_id && project.out_of_sync && <LazyPart quiet><SyncChip videoId={project.video_id} compact onSettled={() => void settleSync(project.video_id)} /></LazyPart>}
          </div>
          ) : null}
          <span className="text-faint max-[1600px]:hidden" aria-hidden="true">/</span>
          <h1 className="disp m-0 min-w-0 max-w-[28ch] truncate text-[15px] font-semibold lg:max-w-none lg:flex-[1_1_0]" title={project.filename}>{project.filename}</h1>
          <span className="tag text-faint max-[1600px]:hidden">{timecode(project.duration)}{speakers.length > 0 ? ` · ${speakers.length} ${speakers.length === 1 ? 'voice' : 'voices'}` : ''}</span>
          <div className="segs" role="group" aria-label="Play" data-tour="playback-switch">
            {views.map(([v, label, on, why]) => (
              <button key={v} type="button" className="seg disabled:cursor-not-allowed disabled:opacity-45" aria-pressed={view === v} onClick={() => switchView(v)} disabled={!on}
                title={!on ? why : v === 'final' ? 'The video with the lines you added (O)' : v === 'original' ? 'The video as shot, without your changes (O)' : 'Edited, plus the proposals waiting for you'}>
                {v === 'proposals' && !previewReady && previewing ? `${label}…` : label}
              </button>
            ))}
          </div>
          <span className="flex-1 lg:hidden" />
          {!watching && <button type="button" className="act" onClick={() => { setMayDoOpen(true); tour.notify('autonomy-opened') }} data-tour="autonomy" data-tour-action="autonomy" aria-haspopup="dialog" aria-label={`${autonomy === 'ask' ? 'Check with me' : 'Just do it'}. What Voltage may do`}>
            <span className="tag">{autonomy === 'ask' ? 'Check with me' : 'Just do it'}</span>
            <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>}
          <SpendPill summary={spend} videoId={project.video_id} />
          {!watching && <a className={cn('btn ink sm', exporting && 'opacity-70')} href={hrefFor({ page: 'export', projectId: project.video_id })} aria-busy={exporting || undefined} data-tour="export" data-tour-action="export">
            {exporting ? 'Rendering…' : 'Export'}
          </a>}
          <NotificationBell />
          <AccountDot me={me} />
          {batchOn && languagesOpen && <LazyPart quiet><LanguageDialog videoId={project.video_id} filename={project.filename} projectId={project.project_id} onClose={() => setLanguagesOpen(false)}
            onMade={(pid) => { setLanguagesOpen(false); if (pid) go({ page: 'folder', projectId: pid }) }} /></LazyPart>}
          {reviewOn && reviewOpen && <LazyPart quiet><SendForReview target={{ kind: 'video', videoId: project.video_id, title: project.filename }} onClose={() => setReviewOpen(false)}
            onSent={() => setProject((p) => (p ? { ...p, stage: 'in_review' } : p))} /></LazyPart>}
          <WhatVoltageMayDo open={mayDoOpen} value={mayDo} onChange={(c) => void changeMayDo(c)} onClose={() => setMayDoOpen(false)} />
        </header>
        <StatusStrip state={strip} open={activityOpen} onOpen={openActivity} onStop={canStop ? () => void stopAll() : undefined} stopping={stopping} />
  
        <div className="flex min-h-0 flex-1 max-[960px]:flex-col">
          {/* The picture, the transport, the transcript. */}
          <main id="main" tabIndex={-1} className="slimbar min-h-0 min-w-0 flex-1 overflow-y-auto outline-none max-[960px]:overflow-visible" aria-busy={turnBusy || undefined}>
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
                notice={renderNote}
                onPlayingChange={setPlayerPlaying}
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
              {discardWhy && projectId && <DiscardWhy key={discardWhy.decisionId} videoId={projectId} decisionId={discardWhy.decisionId} line={discardWhy.line} reasons={DISCARD_REASONS} onClose={() => setDiscardWhy(null)} />}
              {stageAsk && <StageWarning className="fixed bottom-6 left-1/2 z-40 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 shadow-volt" message={stageAsk.message} anyway={stageAsk.anyway} onCancel={() => setStageAsk(null)} onAnyway={() => { const run = stageAsk.run; setStageAsk(null); run() }} />}
              {firstRead && speakers.length > 0 && (
                <WhoSpeaks speakers={speakers} statements={statements} reading={readingBusy ? null : reading} onName={(label, name) => void changeSpeaker(label, { name })} />
              )}
              {firstRead && speakers.length === 0 && statements.length > 0 && (
                <div className="flex items-center gap-3 rounded-xl border-[1.5px] border-line2 bg-card p-4">
                  <span className="meta flex-1">Voltage hasn't told the speakers apart yet.</span>
                  {!watching && <button type="button" className="btn sm" onClick={() => void findSpeakers()} disabled={detecting} aria-busy={detecting || undefined}>{detecting ? 'Listening…' : 'Find who speaks'}</button>}
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
                disabled={turnBusy || watching}
                usdPerChar={usdPerChar}
                playing={playingTake}
                onSeek={seekToStatement}
                onHear={hearLine}
                onAdd={(item) => addItem(item)}
                onDiscard={(item) => discardItem(item)}
                onAddAll={(items) => approveAll(items)}
                onHearTake={(_item, c) => playTake(c)}
                onRole={(target, change) => changeRole(target, change)}
                mixLines={(version === 'proposals' ? preview?.mix : finalMix)?.lines ?? []}
                bedUnderDb={project.settings?.mix?.bed_under_db ?? 15}
                onDelivery={(item, delivery) => void takeTurn(`Voice ${item.item_id} again, said ${delivery}`)}
            onRetry={(item) => void takeTurn(`Try ${item.item_id} again (“${item.new_text}”): ${item.error ?? 'the last try failed'}`)}
                onShorten={(item) => void takeTurn(shortenSentence([item]))}
                onShortenAll={(items) => void takeTurn(shortenSentence(items))}
                onEase={(item) => easeLine(item)}
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
                activity={rowActivity}
                bannedWords={projectRules.filter((r) => r.kind === 'banned').map((r) => r.data.word ?? '').filter(Boolean)}
              />
              {consistency && project.project_id && (
                <LearnWord projectId={project.project_id} projectName={project.project_name} onAdded={(rule) => setProjectRules((r) => [...r, rule])} />
              )}
              {reviewOn && (
                <div className="flex flex-wrap items-center gap-3 rounded-xl border-[1.5px] border-line2 bg-card px-4 py-3">
                  <span className="flex-1 text-sm text-muted-foreground">{project.stage === 'in_review' ? 'In review. Comments from the review link show here and on the scrubber.' : 'Send a link so a client can watch, comment at a moment, and approve.'}</span>
                  <button type="button" className="btn sm" onClick={() => setReviewOpen(true)} aria-haspopup="dialog" data-testid="send-review-open">Send for review</button>
                </div>
              )}
              {safetyOn && !watching && (project.consent_granted_at || withdrew) && (
                <WithdrawConsent videoId={project.video_id} onWithdrawn={() => { consentGiven.current = false; setWithdrew(true); setProject((p) => (p ? { ...p, consent_granted_at: null } : p)) }} />
              )}
              {reviewOn && (
                <LazyPart>
                  <ReviewComments videoId={project.video_id} comments={review.comments} error={review.error} busy={turnBusy}
                    onReload={review.reload} onChanged={review.replace}
                    onSeek={(time) => { setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 })); setCurrentTime(time) }}
                    onAsk={(goal) => void takeTurn(goal)} />
                </LazyPart>
              )}
            </div>
          </main>
  
          {/* Voltage: black in both themes. */}
          <aside className="pane flex min-h-0 w-[400px] min-w-0 max-w-full shrink-0 flex-col overflow-clip max-[960px]:h-[85dvh] max-[960px]:min-h-[60dvh] max-[960px]:w-auto" aria-label="Voltage" aria-busy={turnBusy || undefined}>
            <VoltagePane
              readOnly={watching ? REVIEWER_NOTE : null}
              messages={messages}
              projectId={project.video_id}
              state={stateWord}
              busy={turnBusy || readingBusy}
              need={clarifying}
              engine={engine}
              chips={contextChips}
              cap={`Turn cap $${mayDo.turn_usd.toFixed(2)}`}
              spend={spend}
              question={question}
              picked={picked}
              steps={steps}
              summary={summary}
              onAnswer={(o, allowMore) => void clarify(o, allowMore)}
              turnCap={mayDo.turn_usd}
              onSubmit={submitComposer}
              inputRef={composerRef}
              seed={seed}
              onShowMe={showMe}
              placeholder={placeholder}
              sendLabel={sendLabel}
              working={turnBusy ? (turnStep ?? 'Working…') : null}
              suggestions={readingBusy ? [] : suggestions}
              onChipEvent={(event, c, edited) => { if (projectId) chipEvent(projectId, event, c.kind, c.label, edited) }}
              seeing={seen && (seen.read || seen.beats.length > 0) ? (
                <WhatISee
                  key={`${seen.version}-${seen.corrections.length}`}
                  seen={seen} disabled={turnBusy || readingBusy} defaultOpen={messages.length === 0}
                  onSeek={(t) => { const time = shown ? renderTimeFrom(t, shown.pieces) : t; setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 })); setCurrentTime(time) }}
                  onCorrect={async (change) => { if (projectId) { try { setSeen(await correctUnderstanding(projectId, change)) } catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save that correction.') } } }}
                  onStyle={async (line) => { if (projectId) { try { setSeen(await setStyle(projectId, line)) } catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save the style.') } } }}
                />
              ) : undefined}
              before={firstRead ? (
                <div className="flex flex-col gap-3.5" data-testid="first-read">
                  {readingBusy && !reading ? (
                    <p className="pm m-0 text-[15px]" role="status">Taking the video in…</p>
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
          <ConsentSheet who={consentAsk.who} busy={consenting} livenessVideoId={safetyOn ? project.video_id : null} onConfirm={(id) => void confirmConsent(id)} onCancel={() => setConsentAsk(null)} />
        )}
        {firstTip && <Tip key={firstTip.id} id={firstTip.id} target={firstTip.target} />}
        <KeyboardSheet open={keysOpen} onClose={() => setKeysOpen(false)} />
        <ActivityDrawer open={activityOpen} onClose={() => { setActivityOpen(false); setAllJobs(null) }} onRetry={retry}
          jobs={(allJobs ?? []).reduce((all, j) => (all.some((k) => k.job_id === j.job_id) ? all : [...all, j]), activity.jobs).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))} />
        <Toaster toast={toast} onAction={onToastAction} onDismiss={() => setToast(null)} />
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
      </FeedbackProvider>
    )
  })()
  const showChecklist = me !== null && !(me.mode !== 'off' && (!me.user || signedOut)) && !project?.settings?.tutorial
  return (
    <>
      {page}
      {showChecklist && <Checklist onShowMe={showMe} />}
      {me !== null && !(me.mode !== 'off' && (!me.user || signedOut)) && <FeedbackHost />}
    </>
  )
}
