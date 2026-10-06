import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { ConsentSheet } from './components/ConsentSheet'
import { SignIn } from './components/SignIn'
import { ShipSheet } from './components/ShipSheet'
import type { Shipped } from './components/ShipSheet'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import type { Block } from './components/Player'
import { captionAt } from './transcript/caption'
import type { CaptionPending } from './transcript/caption'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { CandidateCard } from './components/CandidateCard'
import { QuestionCard } from './components/QuestionCard'
import { ExportBar } from './components/ExportBar'
import { ProjectList } from './components/ProjectList'
import { SpendMeter } from './components/SpendMeter'
import { LineDoc } from './components/LineDoc'
import type { LineRequest, LineState, PendingLine, FitReadout } from './components/LineDoc'
import { keyOf } from './transcript/keys'
import type { LineKey } from './transcript/keys'
import { PlanCard } from './components/PlanCard'
import { ReviewPanel } from './components/ReviewPanel'
import { ActivityLog } from './components/ActivityLog'
import { ReadingCard } from './components/ReadingCard'
import { AutonomySwitch } from './components/AutonomySwitch'
import { Orb } from './components/Orb'
import { VoicePicker } from './components/VoicePicker'
import { SpeakersBar } from './components/SpeakersBar'
import { clock } from './transcript/format'
import { speakerSlot } from './transcript/speakers'
import {
  createProject, confirmPlace, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject, getUsage, listVoices, updateSpeaker, detectSpeakers,
  revertEdit, updateSettings, rewordLine, removeLine, moveCandidate, moveEdit, shiftLine,
  createPlan, getPlan, updateItem, runPlan, answerItem, redoItem, approvePlan, clarifyPlan,
  readProject, revisePlan, stopPlan, grantConsent, createVariant, getMe, logout,
} from './api'
import type { Me } from './api'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage, Question, QuestionOption,
  Fit, Mix, Insert, ProjectSummary, Usage, Statement, Voice, Revision, LongLines,
  Plan, PlanItem, Autonomy, Reading,
} from './types'
import { renderTime, sourceTime } from './timeline/selection'
import styles from './App.module.css'

/** Smooth scrolling and motion are the user's call (UX-6). */
const prefersReducedMotion = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'
// Until the voice list loads: the server's configured default voice.
const DEFAULT_VOICE = 'speaker-1'

/** An answer to a question: the line already read, and the choices so far. */
interface Answer { text: string; fit?: Fit; mix?: Mix; on_long?: LongLines; delivery?: string }

type Stage = 'load' | 'editor'

/** Words that mean "take your guess" when Voltage has asked something. */
const GO = /^(go|ok|okay|yes|sure|go ahead|fine|yep|do it)[.!]?$/i

/** The chat's voice, or the speaker's own, named for a take. */
const voiceName = (voices: Voice[], id: string) => voices.find((v) => v.voice_id === id)?.name

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
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  // The span the open take was asked for — a line that ran into the pause
  // after it ends later than this.
  const [asked, setAsked] = useState<Selection | null>(null)
  // The open question, with the request it is about — answering re-sends that
  // request for the same selection, plus the choice.
  const [question, setQuestion] = useState<
    { question: Question; prompt: string; selection: Selection } | null
  >(null)
  const [generating, setGenerating] = useState(false)
  const [working, setWorking] = useState<Selection | null>(null)
  const [progress, setProgress] = useState<{ value: number; step: string } | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [inserts, setInserts] = useState<Insert[]>([])
  const [download, setDownload] = useState<{ url: string; filename: string } | null>(null)
  const [exporting, setExporting] = useState(false)
  // UX-6: how much of the upload has gone, 0..1; null when not uploading.
  const [uploadShare, setUploadShare] = useState<number | null>(null)
  // The latest render of the approved edits, and which version the player shows.
  const [rendered, setRendered] = useState<{ url: string; duration: number } | null>(null)
  const [view, setView] = useState<'original' | 'edited'>('original')
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState(DEFAULT_VOICE)
  const [seekRequest, setSeekRequest] = useState<{ time: number; id: number; play?: boolean; until?: number } | null>(null)
  const [detecting, setDetecting] = useState(false)
  // Approved edits still in force, shown as tracked changes in the transcript.
  const [approved, setApproved] = useState<Revision[]>([])
  // How this project places a line that runs long; remembered on the server.
  const [longLines, setLongLines] = useState<LongLines>('pause')
  // The agent (Phase 13): how much it does on its own, its latest plan, and
  // the job voicing that plan.
  const [autonomy, setAutonomy] = useState<Autonomy>('ask')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planning, setPlanning] = useState(false)
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
  const [planBusy, setPlanBusy] = useState(false)
  const [planProgress, setPlanProgress] = useState<{ value: number; step: string } | null>(null)
  const [review, setReview] = useState(false)
  // UX-7d: Keep or Hold per change, decided in the script; a take that failed its sound check starts held.
  const [decisions, setDecisions] = useState<Record<string, 'keep' | 'hold'>>({})
  // While Voltage reads, the transcript line it is "on" is lit in turn.
  const [readingAt, setReadingAt] = useState(0)
  // The line open in the hands-on editor, so the panel can stand by.
  const [editingLine, setEditingLine] = useState<Statement | null>(null)
  const [showPlanWhileEditing, setShowPlanWhileEditing] = useState(false)
  // How the last take on each line was made to fit, for the editor's readout.
  const [readouts, setReadouts] = useState<FitReadout[]>([])
  // Hands-on work, line by line: takes to choose from, questions, errors.
  const [lines, setLines] = useState<Record<LineKey, LineState>>({})
  // The take playing in place of the line, with its own audio under the video.
  const [playingTake, setPlayingTake] = useState<string | null>(null)
  const takeAudio = useRef<HTMLAudioElement | null>(null)
  // The word timeline is for exact spans; hidden until asked for.
  const [precise, setPrecise] = useState(false)
  // A take or kept line being dragged to a new start on the bar.
  const [placing, setPlacing] = useState<{ id: string; start: number; duration: number } | null>(null)
  const composerRef = useRef<HTMLInputElement>(null)
  const previewToken = useRef(0)
  const planToken = useRef(0)

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
    previewToken.current += 1 // abandon any poll in flight
    setProject(null)
    setTranscript([])
    setSelection(null)
    setCurrentTime(0)
    setMessages([])
    setCandidate(null)
    setAsked(null)
    setQuestion(null)
    setGenerating(false)
    setWorking(null)
    setProgress(null)
    setSegments([])
    setInserts([])
    setDownload(null)
    setRendered(null)
    setView('original')
    setError(null)
    setUsage(null)
    setApproved([])
    setLongLines('pause')
    planToken.current += 1
    setAutonomy('ask')
    setPlan(null)
    setReading(null)
    setReadingBusy(false)
    setPlanning(false)
    setPlanBusy(false)
    setPlanProgress(null)
    setReview(false)
    setShipped(null)
    setConsentAsk(null)
    consentGiven.current = false
    setEditingLine(null)
    setReadouts([])
    setLines({})
    setPlayingTake(null)
    setPlacing(null)
    takeAudio.current?.pause()
  }

  const setLine = (key: LineKey, patch: Partial<LineState> | null) =>
    setLines((all) => {
      if (patch === null) { const { [key]: _, ...rest } = all; return rest }
      const prev: LineState = all[key] ?? { status: 'working', takes: [] }
      return { ...all, [key]: { ...prev, ...patch } }
    })

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

  // Voltage's eye moves down the transcript while it reads.
  useEffect(() => {
    if (!planning) return
    const n = project?.statements?.length ?? 0
    if (n === 0) return
    const timer = setInterval(() => setReadingAt((i) => (i + 1) % n), 350)
    return () => clearInterval(timer)
  }, [planning, project?.statements?.length])

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
      .then((r) => {
        setVoices(r.voices)
        setVoiceId((v) => (v === DEFAULT_VOICE ? r.default : v))
      })
      .catch(() => {}) // without the list, edits use the default voice
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
    setLongLines(loaded.settings?.long_lines ?? 'pause')
    setAutonomy(loaded.settings?.autonomy ?? 'ask')
    setPlan(loaded.plan ?? null)
    setReading(loaded.reading ?? null)
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

  /** Whose voice a span belongs to, for the consent sentence: "the Shopkeeper". */
  const whoAt = (at: Selection | null | undefined) => {
    if (!at) return null
    const st = (project?.statements ?? []).find((x) => x.start < at.end && at.start < x.end)
    const name = project?.speakers?.find((sp) => sp.label === st?.speaker)?.name
    return name ? (/^Speaker /.test(name) ? name : `the ${name}`) : null
  }

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

  const runPreview = async (
    prompt: string,
    answer?: Answer,
    at: Selection | null = selection,
    shown: string = prompt,
    voice: string = voiceId,
    line?: { key: LineKey; request: LineRequest },
  ) => {
    if (!projectId || !at) return
    if (!consentGiven.current) {
      return withConsent(whoAt(at), () => void runPreview(prompt, answer, at, shown, voice, line))
    }
    say({ role: 'user', text: shown })
    setError(null)
    if (line) {
      setLine(line.key, { status: 'working', question: null, error: null, progress: 'Voicing the line…', request: line.request })
    } else {
      setCandidate(null)
      setQuestion(null)
      setGenerating(true)
      setWorking(at)
    }
    setAsked(at)
    setProgress({ value: 0, step: 'Queued' })

    // A newer prompt supersedes an older one; the stale poll stops rather than
    // racing to overwrite the newer candidate.
    const token = ++previewToken.current
    const superseded = () => previewToken.current !== token

    try {
      const job = await previewEdit(projectId, {
        prompt,
        start: at.start,
        end: at.end,
        voice_profile_id: voice,
        ...(shown !== prompt ? { display: shown } : {}),
        ...answer,
      })
      const finished = await pollJob(job.job_id, {
        shouldStop: superseded,
        onUpdate: (j) => {
          setProgress({ value: j.progress, step: j.step })
          if (line) setLine(line.key, { progress: j.step })
        },
      })
      if (superseded()) return

      const result = finished.result
      if (finished.status === 'failed' || !result) {
        if (line) setLine(line.key, { status: 'failed', error: finished.error ?? "Couldn't voice it. Try again.", progress: null })
        else setError(finished.error ?? 'Preview failed. Try again.')
        return
      }
      if (result.type === 'reply') {
        say({ role: 'assistant', text: result.text })
        if (line) setLine(line.key, null)
        return
      }
      if (result.type === 'question') {
        say({ role: 'assistant', text: result.question })
        if (line) setLine(line.key, { status: 'needs-you', question: result, progress: null })
        else setQuestion({ question: result, prompt, selection: at })
        return
      }
      if (!('candidate_id' in result)) return   // a plan's job, not a preview's
      if (line) {
        setLines((all) => ({ ...all, [line.key]: { ...all[line.key], status: 'ready', takes: [...(all[line.key]?.takes ?? []), result], progress: null, question: null } }))
      } else {
        setSelection(result.plan.selection) // the backend's snapped range
        setCandidate(result)
      }
      const over = result.plan.mix === 'layer' ? 0 : result.plan.selection.end - at.end
      const notes = result.fit_notes ?? []
      const tags = [
        ...(result.plan.new_text !== (answer?.text ?? result.plan.new_text) ? ['shortened to fit'] : []),
        ...notes,
        ...(over > 0.01 && result.plan.mix !== 'concatenate' ? [`ran ${over.toFixed(1)} s into the pause`] : []),
        ...(result.plan.fit === 'stretch' ? ['voice sped up to fit'] : notes.some((n) => n.includes('speed')) ? [] : ['voice at natural speed']),
        'picture untouched',
      ]
      setReadouts((rs) => [...rs.filter((r) => r.selection.start !== at.start || r.selection.end !== at.end), { selection: at, tags }])
    } catch (e) {
      if (e instanceof PollCancelled) return
      const message = e instanceof ApiError ? e.message : 'Preview failed. Try again.'
      if (line) setLine(line.key, { status: 'failed', error: message, progress: null })
      else setError(message)
    } finally {
      if (!superseded() && !line) {
        setGenerating(false)
        setWorking(null)
        setProgress(null)
      }
      void refreshUsage(projectId)
    }
  }

  /** A line edited at the line (UX-1): hear it, keep it, another take, undo. */
  const hearLine = (key: LineKey, request: LineRequest) => {
    // UX-5: a voice-over placed by time on a clip with no speech — the chosen
    // span is the selection, the line plays over the sound there.
    if (request.mix === 'layer') {
      setPlaced((p) => (p.some((x) => x.start === request.selection.start && x.end === request.selection.end) ? p : [...p, request.selection]))
      void runPreview(
        `Add the line "${request.text}"`,
        { text: request.text, mix: 'layer', on_long: request.onLong, ...(request.delivery ? { delivery: request.delivery } : {}) },
        request.selection, `Voice-over at ${clock(request.selection.start)}: “${request.text}”`, request.voiceId ?? voiceId, { key, request },
      )
      return
    }
    const s = statementsNow().find((st) => st.start === request.selection.start && st.end === request.selection.end)
    const display = request.mix === 'replace'
      ? `“${s?.text ?? ''}” → “${request.text}”`
      : `Add after ${clock(request.selection.start)}: “${request.text}”`
    // A chosen start: the line goes there, at its natural length — over the
    // sound there, or with the picture held there.
    const placed = request.mix !== 'replace' && request.at != null
    const span = placed ? { start: request.at!, end: request.at! + 0.05 } : request.selection
    const mix = placed ? (request.mix === 'concatenate' ? 'concatenate' : 'layer') : request.mix
    void runPreview(
      request.mix === 'replace' ? `Replace this line with "${request.text}"` : `Add the line "${request.text}"`,
      { text: request.text, mix, on_long: request.onLong, ...(placed ? { fit: 'start' as const } : {}), ...(request.delivery ? { delivery: request.delivery } : {}) },
      span, display, request.voiceId ?? voiceId, { key, request },
    )
  }
  /** A take dragged to a new start: the same audio, placed again, replaces it under the line. */
  const moveTake = async (key: LineKey, c: Candidate, start: number) => {
    if (!projectId) return
    setError(null)
    try {
      const moved = await moveCandidate(projectId, c.candidate_id, { start })
      setLines((all) => ({ ...all, [key]: { ...all[key], takes: all[key].takes.map((t) => (t.candidate_id === c.candidate_id ? moved : t)) } }))
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
      if (await runExport()) setView('edited')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not move the line.')
    }
  }
  // UX-5: on a clip with no speech, the voice-overs placed by hand or by the
  // plan stand where the lines would be, so every row's machinery applies.
  const [placed, setPlaced] = useState<Selection[]>([])
  const placedStatements = (): Statement[] => {
    if (project?.statements?.length) return []
    const spans = [...placed, ...(plan?.items ?? []).filter((i) => i.kind === 'planned' && i.old_text === '').map((i) => i.selection)]
    const seen = new Set<string>()
    return spans.filter((s) => { const k = keyOf(s); if (seen.has(k)) return false; seen.add(k); return true })
      .sort((a, b) => a.start - b.start)
      .map((s) => ({ text: '', start: s.start, end: s.end, speaker: null, placed: true }))
  }
  const statementsNow = (): Statement[] => (project?.statements?.length ? project.statements : placedStatements())

  const keepTake = async (key: LineKey, c: Candidate) => {
    if (!projectId) return
    setError(null)
    try {
      const result = await approveEdit(projectId, c.candidate_id, !c.continuity.passed)
      const { selection: at, new_text: text, mix = 'replace' } = c.plan
      setApproved((a) => [...a, { edit_id: result.edit_id, start: at.start, end: at.end, text, mix }])
      setLine(key, null)
      setDownload(null)
      if (await runExport()) setView('edited')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Keep failed.')
    }
  }
  const anotherTake = (key: LineKey) => {
    const request = lines[key]?.request
    if (request) hearLine(key, request)
  }
  const answerLine = (key: LineKey, option: QuestionOption) => {
    const state = lines[key]
    if (!state?.question || !state.request) return
    const q = state.question
    const request = { ...state.request, text: option.text ?? q.text }
    say({ role: 'user', text: option.label })
    void runPreview(
      `Replace this line with "${request.text}"`,
      { text: request.text, mix: option.mix ?? q.mix ?? request.mix, fit: option.fit ?? undefined, ...(request.delivery ? { delivery: request.delivery } : {}) },
      request.selection, option.label, request.voiceId ?? voiceId, { key, request },
    )
  }
  const removeStatement = async (s: Statement) => {
    if (!projectId) return
    setError(null)
    try {
      const r = await removeLine(projectId, { start: s.start, end: s.end })
      setApproved((a) => [...a, { edit_id: r.edit_id, start: r.selection.start, end: r.selection.end, text: '', mix: 'remove' }])
      setDownload(null)
      if (await runExport()) setView('edited')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not remove that line.')
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
      if (await runExport()) setView('edited')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not move that line.')
    }
  }
  /** Play a take in place: the video runs from the line while the take's
   *  audio plays over it (the original muted for a replacement). */
  const playTake = (c: Candidate) => {
    if (!project) return
    const audio = takeAudio.current ?? (takeAudio.current = new Audio())
    if (playingTake === c.candidate_id) {
      audio.pause()
      setPlayingTake(null)
      return
    }
    audio.src = artifactUrl(project.project_id, c.audio.sha256)
    audio.onended = () => setPlayingTake(null)
    const span = c.plan.selection
    setView('original')
    setSeekRequest((r) => ({ time: span.start, id: (r?.id ?? 0) + 1, play: true, until: span.start + c.audio.duration + 0.3 }))
    setCurrentTime(span.start)
    setPlayingTake(c.candidate_id)
    const started = audio.play() as Promise<void> | undefined
    if (started && typeof started.catch === 'function') started.catch(() => {})
  }

  /** Remember, for this project, what to do when a line runs long. */
  const rememberLongLines = async (value: LongLines) => {
    if (!projectId || value === longLines) return
    setLongLines(value)
    try {
      await updateSettings(projectId, { long_lines: value })
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't save that setting. Try it again.")
    }
  }

  const rememberAutonomy = async (value: Autonomy) => {
    if (!projectId || value === autonomy) return
    setAutonomy(value)
    try {
      await updateSettings(projectId, { autonomy: value })
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't save that setting. Try it again.")
    }
  }

  /** Follows a job voicing the plan, refreshing the plan as it goes. */
  const followPlanJob = async (jobId: string, planId: string) => {
    if (!projectId) return
    const token = ++planToken.current
    const superseded = () => planToken.current !== token
    setPlanBusy(true)
    setPlanProgress({ value: 0, step: 'Queued' })
    let ticks = 0
    let settled = false
    try {
      const finished = await pollJob(jobId, {
        shouldStop: superseded,
        onUpdate: (j) => {
          setPlanProgress({ value: j.progress, step: j.step })
          // The plan carries each line's status; re-read it now and then. A
          // read still in flight when the job ends must not overwrite the result.
          if (ticks++ % 4 === 0) {
            getPlan(projectId, planId).then((p) => { if (!superseded() && !settled) setPlan(p) }).catch(() => {})
          }
        },
      })
      settled = true
      if (superseded()) return
      if (finished.status === 'failed') {
        tell(finished.error ?? 'Voicing the plan failed. Say go again and I\'ll retry it.')
      }
      const result = finished.result
      setPlan(result && 'type' in result && result.type === 'plan' ? result : await getPlan(projectId, planId))
    } catch (e) {
      if (e instanceof PollCancelled) return
      tell(e instanceof ApiError ? e.message : 'Voicing the plan failed. Say go again and I\'ll retry it.')
    } finally {
      if (!superseded()) {
        setPlanBusy(false)
        setPlanProgress(null)
      }
      void refreshUsage(projectId)
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

  /** A goal for the whole video: Voltage plans the edits. */
  const makePlan = async (goal: string) => {
    if (!projectId) return
    if (autonomy === 'draft' && !consentGiven.current) {
      return withConsent(null, () => void makePlan(goal))
    }
    say({ role: 'user', text: goal })
    setError(null)
    setPlanning(true)
    setReview(false)
    try {
      setStage('editor')
      const made = await createPlan(projectId, { goal, voice_profile_id: voiceId })
      setPlan(made)
      say({ role: 'assistant', text: made.question ? made.question.text : made.summary })
      if (made.job_id) void followPlanJob(made.job_id, made.plan_id)
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't plan that. Try saying it another way.")
    } finally {
      setPlanning(false)
      void refreshUsage(projectId)
    }
  }

  /** Answer Voltage's question (or take its guess); it plans again. */
  const clarify = async (answer?: string, allGuesses = false) => {
    if (!projectId || !plan?.question) return
    const said_ = answer ?? (allGuesses ? 'Go with your guesses' : plan.question.guess ?? plan.question.options[0])
    say({ role: 'user', text: said_ })
    setError(null)
    setPlanning(true)
    try {
      const made = await clarifyPlan(projectId, plan.plan_id, answer, allGuesses)
      setPlan(made)
      say({ role: 'assistant', text: made.summary })
      if (made.job_id) void followPlanJob(made.job_id, made.plan_id)
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't plan with that answer. Pick one of the options, or say go.")
    } finally {
      setPlanning(false)
      void refreshUsage(projectId)
    }
  }

  /** Change the plan in your words (UX-2): applied in place, so the takes
   *  already voiced survive. A new goal altogether comes back as a new plan. */
  const revise = async (instruction: string) => {
    if (!projectId || !plan) return
    say({ role: 'user', text: instruction })
    setError(null)
    setPlanning(true)
    setReview(false)
    try {
      const revised = await revisePlan(projectId, plan.plan_id, instruction)
      setPlan(revised)
      say({ role: 'assistant', text: revised.question ? revised.question.text : revised.summary })
      if (revised.job_id) void followPlanJob(revised.job_id, revised.plan_id)
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't change the plan that way. Try saying it another way.")
    } finally {
      setPlanning(false)
      void refreshUsage(projectId)
    }
  }

  /** Stop a running plan after the line it is on; the rest waits as planned. */
  const stop = async () => {
    if (!projectId || !plan) return
    try {
      setPlan(await stopPlan(projectId, plan.plan_id))
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't stop the plan. It will finish the line it's on.")
    }
  }

  /** The box is for the whole video: a goal, or a change to the plan. A
   *  selection on the Precise timeline still previews through it. */
  const submitComposer = (text: string) => {
    if (plan?.status === 'clarifying') return void clarify(GO.test(text.trim()) ? undefined : text)
    if (selection) return void runPreview(text)
    if (plan && plan.status !== 'running' && plan.status !== 'stopping') return void revise(text)
    return void makePlan(text)
  }

  const changeItem = async (item: PlanItem, change: { enabled?: boolean; new_text?: string; include?: boolean; delivery?: string; mix?: Mix }) => {
    if (!projectId || !plan) return
    try {
      setPlan(await updateItem(projectId, plan.plan_id, item.item_id, change))
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't change that item. Try it again.")
    }
  }

  const startJob = async (start: () => Promise<{ job_id: string }>) => {
    if (!projectId || !plan) return
    if (!consentGiven.current) {
      const first = plan.items.find((i) => i.kind === 'planned' && i.enabled)
      return withConsent(whoAt(first?.selection), () => void startJob(start))
    }
    setError(null)
    try {
      const job = await start()
      void followPlanJob(job.job_id, plan.plan_id)
    } catch (e) {
      tell(e instanceof ApiError ? e.message : "I couldn't start that. Say go again.")
    }
  }

  const runThePlan = () => startJob(() => runPlan(projectId!, plan!.plan_id))
  const redoTheItem = (item: PlanItem) => startJob(() => redoItem(projectId!, plan!.plan_id, item.item_id))
  const answerTheItem = (item: PlanItem, option: QuestionOption) => {
    say({ role: 'user', text: option.label })
    return startJob(() => answerItem(projectId!, plan!.plan_id, item.item_id, {
      fit: option.fit ?? undefined, mix: option.mix ?? undefined, text: option.text ?? undefined,
    }))
  }

  /** Ship the ready changes — all of them, or the ones kept — and render;
   *  the rest stay as drafts. Then the sheet says what is in the file. */
  const approveAll = async (items?: string[]) => {
    if (!projectId || !plan) return
    setError(null)
    try {
      const result = await approvePlan(projectId, plan.plan_id, items ? { items } : {})
      setPlan(result.plan)
      const fresh = result.plan.items.filter((i) => i.status === 'approved' && i.edit_id
        && !approved.some((r) => r.edit_id === i.edit_id))
      setApproved((a) => [...a, ...fresh.map((i) => ({
        edit_id: i.edit_id!, start: i.candidate?.plan.selection.start ?? i.selection.start,
        end: i.candidate?.plan.selection.end ?? i.selection.end, text: i.new_text, mix: i.mix,
      }))])
      if (result.export) {
        setSegments(result.export.segments)
        setInserts(result.export.inserts ?? [])
        const stem = (project?.filename ?? 'video').replace(/\.[^.]+$/, '')
        const url = artifactUrl(projectId, result.export.render.sha256)
        const download = { url, filename: `${stem}-edited.mp4` }
        setDownload(download)
        setRendered({ url, duration: result.export.render.duration })
        setView('edited')
        const went = new Set(result.approved.map((a) => a.item_id))
        setShipped({
          items: result.plan.items.filter((i) => went.has(i.item_id)),
          held: result.plan.items.filter((i) => i.status === 'ready').length,
          removed: approved.filter((r) => r.mix === 'remove').length,
          before: project?.duration ?? 0,
          after: result.export.render.duration,
          download,
          spendUsd: result.plan.spend_usd,
        })
      }
      if (result.skipped.length > 0) {
        setError(`${result.skipped.length} ${result.skipped.length === 1 ? 'change' : 'changes'} skipped: the sound check failed. Listen to them, then Redo or approve them one by one.`)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Approve failed.')
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

  /** Hear the seam: the edited video from a moment before the line to a
   *  moment after, where a pasted edit gives itself away. Without a render
   *  yet, the original at that line. */
  const compareItem = (item: PlanItem) => {
    setSelection(item.selection)
    const span = item.candidate?.plan.selection ?? item.selection
    const edited = rendered !== null
    setView(edited ? 'edited' : 'original')
    const from = Math.max(0, (edited ? renderTime(span.start, inserts) : span.start) - 1.5)
    const until = (edited ? renderTime(span.end, inserts) : span.end) + (item.mix === 'concatenate' && item.candidate ? item.candidate.audio.duration : 0) + 1.5
    setSeekRequest((r) => ({ time: from, id: (r?.id ?? 0) + 1, play: true, until }))
    setCurrentTime(from)
  }

  /** Ask Claude for tighter wordings of a line: two, for the editor to offer. */
  const reword = async (s: Statement, draft: string): Promise<string[]> => {
    if (!projectId) return []
    setError(null)
    try {
      const asks = [
        rewordLine(projectId, { start: s.start, end: s.end, draft }),
        rewordLine(projectId, { start: s.start, end: s.end, draft, instruction: 'so it is shorter while keeping every detail, name and number' }),
      ]
      const results = await Promise.allSettled(asks)
      const texts = results.flatMap((r) => (r.status === 'fulfilled' ? [r.value.text] : []))
      if (texts.length === 0) {
        const failed = results.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
        const reason = failed?.reason
        tell(reason instanceof ApiError ? reason.message : "I couldn't come up with a wording just now. Try again in a moment.")
      }
      return Array.from(new Set(texts))
    } finally {
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
    const edited = view === 'edited' && rendered !== null
    const time = edited ? renderTime(s.start, inserts) : s.start
    setSeekRequest((r) => ({ time, id: (r?.id ?? 0) + 1 }))
    setCurrentTime(time)
  }

  const answer = (option: QuestionOption) => {
    if (!question) return
    const { question: q, prompt, selection: at } = question
    void runPreview(prompt, {
      text: q.text,
      mix: option.mix ?? q.mix ?? undefined,
      fit: option.fit ?? undefined,
    }, at, option.label)
  }

  const approve = async (override = false) => {
    if (!projectId || !candidate) return
    setError(null)
    try {
      const result = await approveEdit(projectId, candidate.candidate_id, override)
      const { selection: at, new_text: text, mix = 'replace' } = candidate.plan
      setApproved((a) => [...a, { edit_id: result.edit_id, start: at.start, end: at.end, text, mix }])
      setCandidate(null)
      setAsked(null)
      setDownload(null) // the last render no longer includes every approved edit
      // Render straight away, so pressing Play hears the edit.
      if (await runExport()) setView('edited')
    } catch (e) {
      // Never silently drop the candidate — leave it on screen to iterate on.
      if (e instanceof ApiError && e.status === 422) {
        setError('Continuity check failed — this edit cannot ship.')
      } else {
        setError('Approve failed.')
      }
    }
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
      if (await runExport()) setView('edited')
    } else {
      setRendered(null)
      setSegments([])
      setInserts([])
      setView('original')
    }
  }

  /** Renders the approved edits; true when the render is ready to play. */
  const runExport = async (
    id: string | null = projectId, filename = project?.filename,
  ): Promise<boolean> => {
    if (!id) return false
    setError(null)
    setExporting(true)
    try {
      const manifest = await exportProject(id)
      setSegments(manifest.segments)
      setInserts(manifest.inserts ?? [])
      const stem = (filename ?? 'video').replace(/\.[^.]+$/, '')
      const url = artifactUrl(id, manifest.render.sha256)
      setDownload({ url, filename: `${stem}-edited.mp4` })
      setRendered({ url, duration: manifest.render.duration })
      return true
    } catch {
      setError('Export failed.')
      return false
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
      setApproved(live.map((e) => ({
        edit_id: e.edit_id, start: e.selection.start, end: e.selection.end, text: e.new_text, mix: e.mix, partner: e.partner ?? null,
      })))
      // Approved edits are rendered again, so Play hears them straight away.
      if (live.length > 0 && await runExport(opened.project_id, opened.filename)) {
        setView('edited')
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
      <div className={styles.blank} role="status" aria-busy="true">
        <Orb size={26} working />
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
  const showEdited = view === 'edited' && rendered !== null
  const speakers = project.speakers ?? []
  const statements = statementsNow()
  const leave = () => {
    clearEditor()
    window.location.hash = ''
    setStage('load')
  }

  // Where things stand line by line: the plan's items, and the one edit the
  // chat may be working on.
  const pendingLines: PendingLine[] = [
    ...(planning && statements.length > 0 ? [{ selection: { start: statements[readingAt % statements.length].start, end: statements[readingAt % statements.length].end }, status: 'reading' as const }] : []),
    ...(plan?.items ?? [])
      .filter((i) => i.kind === 'planned' && i.enabled && ['planned', 'working', 'ready', 'needs-you', 'failed'].includes(i.status))
      .map((i) => ({ selection: i.selection, status: i.status, text: i.new_text, mix: i.mix })),
    ...(generating && working ? [{ selection: working, status: 'working' as const }]
      : question ? [{ selection: question.selection, status: 'needs-you' as const }]
      : candidate ? [{ selection: candidate.plan.selection, status: 'ready' as const }]
      : []),
  ]
  const readyCount = plan?.items.filter((i) => i.status === 'ready').length ?? 0
  const reviewable = (plan?.items.filter((i) => i.status === 'ready' || i.status === 'approved').length ?? 0) > 0
  const reviewCount = plan?.items.filter((i) => i.kind === 'planned' && (i.status === 'ready' || i.status === 'approved')).length ?? 0
  const isHeld = (item: PlanItem) => (decisions[item.item_id] ? decisions[item.item_id] === 'hold' : !(item.candidate?.continuity.passed ?? true))
  const readyItems = plan?.items.filter((i) => i.kind === 'planned' && i.status === 'ready') ?? []
  const keptItems = readyItems.filter((i) => !isHeld(i))
  const busy = generating || planBusy || planning
  const clarifying = plan?.status === 'clarifying'
  const planned = plan?.items.filter((i) => i.kind === 'planned' && i.enabled) ?? []
  const doneCount = planned.filter((i) => ['ready', 'approved', 'needs-you', 'failed'].includes(i.status)).length
  const stateWord = planning ? (plan ? 'changing the plan' : 'reading the clip')
    : clarifying ? 'has a question'
    : plan?.status === 'stopping' ? 'stopping after this line'
    : planBusy ? `working · ${doneCount} of ${planned.length} done`
    : editingLine ? 'standing by'
    : plan?.status === 'proposed' ? 'has a plan'
    : review ? 'ready to ship'
    : 'ready'
  const sendLabel = clarifying ? 'Answer'
    : selection ? 'Preview the change'
    : plan && plan.status !== 'running' && plan.status !== 'stopping' ? 'Change the plan'
    : 'Plan it'
  const placeholder = clarifying ? 'Answer, or tell Voltage anything else'
    : review ? "What's off?"
    : selection ? 'Ask for a change, e.g. say "30% off" instead'
    : plan && (plan.status === 'running' || plan.status === 'stopping') ? 'Voicing the plan; Stop it to change it'
    : plan ? 'Change the plan in your words: "not the second one", "warmer at 0:17"'
    : 'What should this video say?'
  const secondsLeft = plan && planBusy ? Math.max(5, Math.round((plan.estimate.seconds || 12) * (1 - (planned.length ? doneCount / planned.length : 0)))) : 0

  // The take's own details: whose line, in which voice, and whether it ran on.
  const takeSpeakerLabel = candidate
    ? statements.find((s) => s.start < candidate.plan.selection.end && candidate.plan.selection.start < s.end)?.speaker
    : null
  const takeSpeaker = speakers.find((s) => s.label === takeSpeakerLabel)
  const takeVoice = candidate ? voiceName(voices, candidate.plan.voice_profile_id) : undefined
  const overrun = candidate && asked ? candidate.plan.selection.end - asked.end : 0
  const ranOn = candidate?.plan.mix !== 'concatenate' && overrun > 0.01

  const sourceClock = showEdited ? sourceTime(currentTime, inserts) : currentTime
  const voiceLine = usage?.lines.find((l) => l.vendor === 'elevenlabs' && l.units > 0)
  const usdPerChar = voiceLine ? voiceLine.usd / voiceLine.units : null
  const playingMix = playingTake
    ? Object.values(lines).flatMap((l) => l.takes).find((c) => c.candidate_id === playingTake)?.plan.mix ?? 'replace'
    : null
  // What is waiting on you, line by line, for the panel's last word.
  const lineEntries = Object.entries(lines)
  const needsYou = lineEntries.filter(([, l]) => l.status === 'needs-you')
  const readyLines = lineEntries.filter(([, l]) => l.status === 'ready')
  const atLine = (key: LineKey) => {
    const i = statements.findIndex((s) => keyOf({ start: s.start, end: s.end }) === key || `add-${s.end.toFixed(3)}` === key)
    document.getElementById(`line-${i}`)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    return i >= 0 ? clock(statements[i].start) : ''
  }
  const timeOf = (key: LineKey) => {
    const i = statements.findIndex((s) => keyOf({ start: s.start, end: s.end }) === key || `add-${s.end.toFixed(3)}` === key)
    return i >= 0 ? clock(statements[i].start) : key
  }
  // UX-7b: the monitor's timeline and caption. Times follow the version that
  // plays: an insert in the edited render pushes everything after it later.
  const toRender = (t: number) => (showEdited ? renderTime(t, inserts) : t)
  const blocks: Block[] = [
    ...statements.map((s) => ({ start: toRender(s.start), end: toRender(s.end), tone: speakerSlot(speakers, s.speaker) as Block['tone'] })),
    ...approved.filter((r) => r.mix !== 'remove').map((r) => ({ start: toRender(r.start), end: toRender(r.end), tone: 'changed' as const })),
    ...pendingLines.filter((l) => l.text).map((l) => ({ start: toRender(l.selection.start), end: toRender(l.selection.end), tone: 'changed' as const })),
  ]
  // A take in hand, not yet kept, is captioned with its words too: the picture
  // shows what you are about to hear.
  const takesInHand: CaptionPending[] = [
    ...Object.values(lines).flatMap((l) => {
      const take = l.takes[l.takes.length - 1]
      return take ? [{ selection: take.plan.selection, text: take.plan.new_text, mix: take.plan.mix }] : []
    }),
    ...(candidate ? [{ selection: candidate.plan.selection, text: candidate.plan.new_text, mix: candidate.plan.mix }] : []),
  ]
  const captionRuns = captionAt(sourceClock, statements, approved, [...pendingLines, ...takesInHand], transcript, rendered !== null && view === 'original')
  const caption = captionRuns?.map((r, k) => <Fragment key={k}>{k > 0 && ' '}{r.kind === 'ins' ? <ins>{r.text}</ins> : r.text}</Fragment>)

  return (
    <div className={styles.app} data-panel={panelHidden ? 'hidden' : undefined}>
      <a className="skip" href="#main">Skip to the transcript</a>
      <header className={styles.header}>
        <button className={styles.back} onClick={leave}>← Projects</button>
        <h1 className={styles.brand}><Orb size={14} />Voltage</h1>
        <span className={styles.slash} aria-hidden="true">/</span>
        <span className={styles.filename} title={project.filename}>{project.filename}</span>
        <span className={styles.meta}>
          {project.duration.toFixed(1)} s{speakers.length > 0 && `, ${speakers.length} ${speakers.length === 1 ? 'speaker' : 'speakers'}`}
        </span>
        <span className={styles.spacer} />
        <SpendMeter usage={usage} />
        {me.user && (
          <span className={styles.who} data-testid="who">
            {me.user.picture ? <img className={styles.face} src={me.user.picture} alt="" referrerPolicy="no-referrer" /> : null}
            <span className={styles.whoName}>{me.user.name ?? me.user.email ?? 'You'}</span>
            <button className={styles.signOut} onClick={() => void signOut()}>Sign out</button>
          </span>
        )}
        {reviewable && (
          <button className={styles.reviewButton} aria-pressed={review} onClick={() => setReview((r) => !r)}>
            {review ? 'Back to the script' : readyCount > 0 ? `Review · ${readyCount} ready` : 'Review'}
          </button>
        )}
        {reviewable && (
          <button
            className={styles.ship}
            onClick={() => void approveAll(keptItems.map((i) => i.item_id))}
            disabled={busy || keptItems.length === 0}
          >
            {keptItems.length === 0 ? 'Ship'
              : keptItems.length === readyItems.length ? `Ship ${keptItems.length} ${keptItems.length === 1 ? 'change' : 'changes'}`
              : `Ship ${keptItems.length} of ${readyItems.length}`}
          </button>
        )}
        <ExportBar segments={segments} inserts={inserts} onExport={() => void runExport()} download={download} busy={exporting} />
      </header>

      <main id="main" className={styles.main} aria-busy={planBusy || undefined}>
        <Player
          src={showEdited ? rendered.url : artifactUrl(project.project_id, project.media.sha256)}
          duration={showEdited ? rendered.duration : project.duration}
          currentTime={currentTime}
          onSeek={setCurrentTime}
          onTimeUpdate={setCurrentTime}
          seekRequest={seekRequest}
          blocks={blocks}
          words={transcript}
          caption={caption}
          muted={playingTake !== null && playingMix === 'replace'}
          placing={placing}
          onPlace={(start) => setPlacing((p) => (p ? { ...p, start } : p))}
        >
          <button className={precise ? styles.preciseOn : styles.precise} aria-pressed={precise} onClick={() => setPrecise((p) => !p)}>Precise</button>
          {rendered && (
            <div className={styles.versions} role="group" aria-label="Version">
              {(['edited', 'original'] as const).map((v) => (
                <button
                  key={v}
                  className={view === v ? styles.versionOn : styles.version}
                  aria-pressed={view === v}
                  onClick={() => { setView(v); setCurrentTime(0) }}
                >
                  {v === 'edited' ? 'Edited' : 'Original'}
                </button>
              ))}
            </div>
          )}
        </Player>
        {error && <div className={styles.error} role="alert">{error}</div>}
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
        <SpeakersBar
          speakers={speakers}
          voices={voices}
          hasSpeech={transcript.length > 0}
          detecting={detecting}
          onDetect={() => void findSpeakers()}
          onRename={(label, name) => void changeSpeaker(label, { name })}
          onVoice={(label, id) => void changeSpeaker(label, id ? { voice_id: id } : { clear_voice: true })}
        />
        <LineDoc
          statements={statements}
          words={transcript}
          speakers={speakers}
          voices={voices}
          revisions={approved}
          selection={selection}
          currentTime={sourceClock}
          pendingLines={pendingLines}
          lines={lines}
          longLines={longLines}
          disabled={planBusy || planning}
          usdPerChar={usdPerChar}
          playing={playingTake}
          readouts={readouts}
          onSeek={seekToStatement}
          onHear={hearLine}
          onKeep={(key, c) => keepTake(key, c)}
          onAnother={anotherTake}
          onAnswer={answerLine}
          onUndo={(id) => void revert(id)}
          onRemove={(s) => void removeStatement(s)}
          onShift={(s, to) => void shiftStatement(s, to)}
          onPlayTake={playTake}
          onDismiss={(key) => setLine(key, null)}
          onMove={(key, c, start) => void moveTake(key, c, start)}
          onMoveKept={(id, start) => void moveKept(id, start)}
          placing={placing}
          onPlacing={setPlacing}
          onReword={reword}
          onLongLinesChange={(v) => void rememberLongLines(v)}
          onEditingChange={setEditingLine}
          duration={project.duration}
          filter={reviewable && plan ? { count: reviewCount, on: review, onChange: setReview } : undefined}
          review={review && plan ? (
            <ReviewPanel
              plan={plan}
              speakers={speakers}
              projectId={project.project_id}
              busy={busy}
              onCompare={compareItem}
              onRedo={(item) => void redoTheItem(item)}
              onUndo={(item) => { if (item.edit_id) void revert(item.edit_id) }}
              isHeld={isHeld}
              onDecide={(item, keep) => setDecisions((d) => ({ ...d, [item.item_id]: keep ? 'keep' : 'hold' }))}
            />
          ) : undefined}
        />
      </main>

      {panelHidden ? (
        <aside className={styles.rail} aria-label="Voltage, tucked away" data-testid="rail">
          <button className={styles.railShow} onClick={showPanel} aria-label={`Show Voltage. ${stateWord[0].toUpperCase()}${stateWord.slice(1)}`}>
            <Orb size={26} working={busy} idle={!busy && !plan} />
          </button>
          {(needsYou.length > 0 || readyLines.length > 0) && (
            <span className={styles.railBadge} data-tone={needsYou.length > 0 ? 'rose' : undefined} aria-hidden="true">{needsYou.length > 0 ? needsYou.length : readyLines.length}</span>
          )}
          <span className={styles.railWord} aria-hidden="true">{stateWord}</span>
          <span className={styles.spacer} />
          <button className={styles.railOpen} onClick={showPanel}>Open</button>
          <button className={styles.railShow} onClick={showPanel} aria-label="Show Voltage">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m15 6-6 6 6 6" /></svg>
          </button>
        </aside>
      ) : (
      <aside ref={panelRef} className={styles.panel} aria-label="Voltage" aria-busy={busy || undefined}>
        <ChatPanel
          messages={messages}
          canSubmit
          onSubmit={submitComposer}
          inputRef={composerRef}
          seed={seed}
          placeholder={placeholder}
          sendLabel={sendLabel}
          hint={clarifying ? 'Pick an answer above, or just say "go" and Voltage will use its guess.'
            : selection && precise ? `Talking about the words at ${clock(selection.start)}.`
            : (project.statements?.length ?? 0) === 0 ? 'For the whole video: what it should say, a brief, or ask me to look at it and help.'
            : 'For the whole video: a goal, or a change to the plan. To change one line, click it.'}
          toolbar={<VoicePicker voices={voices} value={voiceId} onChange={setVoiceId} />}
          header={
            <div className={styles.panelHead}>
              <Orb size={26} working={busy} idle={!busy && !plan} />
              <h2 className={styles.panelTitle}>Voltage</h2>
              <span className={styles.panelNote} role="status">{stateWord}</span>
              <span className={styles.spacer} />
              <AutonomySwitch value={autonomy} onChange={(v) => void rememberAutonomy(v)} />
              <button className={styles.hide} onClick={() => setPanelHidden(true)} aria-label="Hide Voltage. Press backslash to show it again">
                Hide <kbd aria-hidden="true">\</kbd>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
              </button>
            </div>
          }
        >
          {!plan && messages.length === 0 && !generating && !planning && (
            <ReadingCard
              project={project}
              reading={readingBusy ? null : (reading ?? undefined)}
              speakers={speakers}
              onName={(label, name) => void changeSpeaker(label, { name })}
              onPlace={(place) => void confirmThePlace(place)}
              onExample={(text) => setSeed({ text, id: Date.now() })}
            />
          )}
          {planning && !plan && (
            <div className={styles.skeleton} aria-hidden="true" data-testid="skeleton">
              <span /><span /><span />
            </div>
          )}
          {(planning || clarifying) && (
            <div className={styles.thinking} data-testid="thinking">
              {(plan?.findings ?? []).map((f, i) => (
                <div key={i} className={styles.thought} style={{ animationDelay: `${i * 220}ms` }}>
                  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                    <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
                    <path d="M5 8.2l2 2 4-4.4" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>{f}</span>
                </div>
              ))}
              {planning && (
                <div className={`${styles.thought} ${styles.thoughtLive}`} data-testid="planning" role="status">
                  <span className={styles.spinner} aria-hidden="true" />
                  <span>{plan?.question ? 'Planning with your answer…' : 'Reading every line, and who says it…'}<span className={styles.caret} aria-hidden="true" /></span>
                </div>
              )}
            </div>
          )}
          {clarifying && plan?.question && !planning && (
            <div className={styles.question} data-testid="clarify">
              <div className={styles.questionText}>One thing before I plan. <strong>{plan.question.text}</strong></div>
              <div className={styles.questionOptions}>
                {plan.question.options.map((o) => (
                  <button key={o} className={o === plan.question?.guess ? styles.optionOn : styles.option} onClick={() => void clarify(o)}>{o}</button>
                ))}
              </div>
              <div className={styles.questionNote} role="status">
                {(plan.questions_left ?? 0) > 0 && (project.statements?.length ?? 0) === 0 ? `Question ${(plan.answers?.length ?? 0) + 1} of up to 3. ` : ''}
                {plan.question.guess ? `My guess is ${plan.question.guess}. ` : ''}Pick one, or just say "go" and I'll use that.
              </div>
              {(project.statements?.length ?? 0) === 0 && (plan.questions_left ?? 0) > 1 && (
                <div className={styles.questionOptions}>
                  <button className={styles.option} onClick={() => void clarify(undefined, true)}>Go with your guesses</button>
                </div>
              )}
            </div>
          )}
          {editingLine && !planBusy && (
            <div className={styles.welcome}>
              You're on {clock(editingLine.start)}. I'll stay out of the way while you write; ask for wording and I'll offer a couple of tighter lines.
            </div>
          )}
          {plan && editingLine && plan.status === 'done' && !showPlanWhileEditing && (
            <button className={styles.earlier} onClick={() => setShowPlanWhileEditing(true)}>
              Earlier: {plan.items.filter((i) => i.status === 'approved').length} changes shipped · Show
            </button>
          )}
          {plan && (review || plan.status === 'done') && !(editingLine && plan.status === 'done' && !showPlanWhileEditing) && (
            <ActivityLog plan={plan} />
          )}
          {(needsYou.length > 0 || readyLines.length > 0) && !generating && (
            <div className={styles.nextAction} data-testid="line-action">
              <span className={styles.nextText}>
                {needsYou.length > 0
                  ? `${needsYou.length === 1 ? 'One line needs' : `${needsYou.length} lines need`} you, at ${timeOf(needsYou[0][0])}.`
                  : `${readyLines.length === 1 ? 'One line is' : `${readyLines.length} lines are`} ready to hear.`}
              </span>
              <button className={styles.nextButton} onClick={() => atLine((needsYou[0] ?? readyLines[0])[0])}>
                {needsYou.length > 0 ? 'Go to it' : readyLines.length === 1 ? 'Go to it' : 'Go to the first'}
              </button>
            </div>
          )}
          {plan && !clarifying && !(editingLine && plan.status === 'done' && !showPlanWhileEditing) && (
            <PlanCard
              plan={plan}
              speakers={speakers}
              voices={voices}
              projectId={project.project_id}
              busy={planBusy}
              onToggle={(item, enabled) => changeItem(item, { enabled })}
              onReword={(item, text) => changeItem(item, { new_text: text })}
              onInclude={(item, include) => changeItem(item, { include })}
              onRun={() => runThePlan()}
              onAdjust={() => composerRef.current?.focus()}
              onAnswer={(item, option) => answerTheItem(item, option)}
              onRedo={(item) => redoTheItem(item)}
              onApproveAll={() => setReview(true)}
              onDelivery={(item, delivery) => changeItem(item, { delivery: delivery ?? '' })}
              onMix={(item, mix) => changeItem(item, { mix })}
              onStop={() => stop()}
            />
          )}
          {planBusy && (
            <div className={styles.generating} data-testid="plan-progress" role="status">
              <div className={styles.progressRow}>
                <div className={styles.progressTrack} role="progressbar" aria-label="Voicing the plan" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((planProgress?.value ?? 0) * 100)}>
                  <div className={styles.progressFill} style={{ transform: `scaleX(${Math.min(1, Math.max(0, planProgress?.value ?? 0))})` }} />
                </div>
                <span className={styles.progressNote}>about {secondsLeft} s left</span>
              </div>
            </div>
          )}

          {generating && (
            <div className={styles.generating} data-testid="generating">
              <div className={styles.generatingStep} role="status">
                <span className={styles.spinner} aria-hidden="true" />
                {progress?.step ?? 'Queued'}
              </div>
              <div className={styles.progressTrack} role="progressbar" aria-label="Making the take" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((progress?.value ?? 0) * 100)}>
                <div
                  data-testid="progress-bar"
                  className={styles.progressFill}
                  style={{ transform: `scaleX(${Math.min(1, Math.max(0, progress?.value ?? 0))})` }}
                />
              </div>
            </div>
          )}
          {question && <QuestionCard question={question.question} onChoose={answer} />}
          {candidate && (
            <>
              {ranOn && longLines === 'pause' && (
                <div className={styles.remembered}>
                  Longer lines run into the pause after them in this project.{' '}
                  <button onClick={() => void rememberLongLines('ask')}>Ask me each time instead</button>
                </div>
              )}
              <CandidateCard
                candidate={candidate}
                onApprove={() => approve()}
                onApproveAnyway={() => approve(true)}
                onTryAgain={() => { setCandidate(null); setAsked(null) }}
                projectId={project.project_id}
                label={`The change at ${clock(candidate.plan.selection.start)}${takeVoice ? `, ${takeVoice}'s voice` : ''}`}
                speaker={takeSpeaker ? { name: takeSpeaker.name, slot: speakerSlot(speakers, takeSpeaker.label) } : null}
                note={ranOn ? `Ran ${overrun.toFixed(1)} s into the pause after it` : null}
              />
            </>
          )}
        </ChatPanel>
      </aside>
      )}
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
          onClose={() => { setShipped(null); setReview(false) }}
        />
      )}
    </div>
  )
}
