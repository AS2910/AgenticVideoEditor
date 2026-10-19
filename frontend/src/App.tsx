import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { ConsentSheet } from './components/ConsentSheet'
import { Player, timecode } from './components/Player'
import type { Marker } from './components/Player'
import { captionAt, takeCaption } from './transcript/caption'
import type { CaptionPending } from './transcript/caption'
import { Timeline } from './components/Timeline'
import { VoltagePane } from './components/VoltagePane'
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
import { VoicesPage } from './pages/VoicesPage'
import { UsagePage } from './pages/UsagePage'
import { SettingsPage } from './pages/SettingsPage'
import { BillingPage } from './pages/BillingPage'
import { LoginPage } from './pages/LoginPage'
import { ExportPage } from './pages/ExportPage'
import { go, hrefFor, useRoute } from './lib/route'
import { cn } from '@/lib/utils'
import { clock } from './transcript/format'
import {
  createProject, confirmPlace, exportProject, artifactUrl, pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject, getUsage, listVoices, updateSpeaker, detectSpeakers, revertEdit, updateSettings, removeLine, dismissItem, setEditLevel, setCandidateLevel, BACKGROUND_DB, moveCandidate, moveEdit, shiftLine, getPlan, approvePlan, readProject, grantConsent, getMe, postTurn, getMessages,
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

// What Voltage may do until the project says otherwise (the server's defaults).
const MAY_DO: MayDo = { autonomy: 'ask', turn_usd: 0.5, effort: 'high', ceiling_usd: 2 }

// The model's short name on the pane's header; an unknown id shows as it is.
const MODEL_NAMES: Record<string, string> = {
  'claude-opus-5-5': 'Opus 5.5', 'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-haiku-5-5': 'Haiku 5.5', 'claude-fable-5-1': 'Fable 5.1',
}

/** What a turn that shipped on its own left behind, for the note in the pane (replaces the ship sheet). */
interface ShippedNote { count: number; held: number; spendUsd: number }

export default function App() {
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
  const [exporting, setExporting] = useState(false)
  const [uploadShare, setUploadShare] = useState<number | null>(null)
  const [rendered, setRendered] = useState<{ url: string; duration: number } | null>(null)
  // 20e: which render plays — the final, the original, or the preview with the proposals mixed in.
  const [view, setView] = useState<'original' | 'final' | 'proposals'>('original')
  const [preview, setPreview] = useState<{ url: string; duration: number; pieces: Piece[]; key: string } | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const asVoice = (v: MyVoice): Voice => ({ voice_id: v.voice_id, name: v.name, description: 'your voice', gender: null, accent: null, age: null, category: 'mine' })
  const takeInVoices = (r: { voices: Voice[]; mine?: MyVoice[] }) => {
    const mine = (r.mine ?? []).map(asVoice)
    setVoices([...mine, ...r.voices.filter((v) => !mine.some((m) => m.voice_id === v.voice_id))])
  }
  const [seekRequest, setSeekRequest] = useState<{ time: number; id: number; play?: boolean; until?: number } | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [approved, setApproved] = useState<Revision[]>([])
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
      setProjects(await listProjects())
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
    setApproved([])
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

  const projectId = project?.project_id ?? null
  const signedIn = me !== null && (me.mode === 'off' || (me.user !== null && !signedOut))

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
    opening.current = loaded.project_id
    go({ page: 'editor', projectId: loaded.project_id })
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
        { edit_id: r.removed_edit_id, start: r.from.start, end: r.from.end, text: '', mix: 'remove', partner: r.edit_id, speaker: s.speaker },
        { edit_id: r.edit_id, start: r.selection.start, end: r.selection.end, text: s.text, mix: 'layer', partner: r.removed_edit_id, speaker: s.speaker },
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
      setPlaceDraft(null)
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
  const submitComposer = (text: string) => void takeTurn(selection && precise ? `At ${clock(selection.start)}: ${text}` : text)

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
    setShippedNote(null)
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

  // Volt: the route decides what is open. The editor and export routes open
  // the project they name (once, by id); the start lists the projects and
  // lets the last one go.
  useEffect(() => {
    if (!signedIn) return
    if (route.page === 'editor' || route.page === 'export') {
      if (opening.current !== route.projectId) { opening.current = route.projectId; void openProject(route.projectId) }
    } else if (route.page === 'projects') {
      if (project) { clearEditor(); opening.current = null }
      void refreshProjects()
    }
    // openProject and clearEditor are stable enough for the route's purposes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, signedIn])

  const signedOutNow = () => {
    clearEditor()
    opening.current = null
    setMe((m) => (m ? { ...m, user: null } : m))
    go({ page: 'projects' })
  }

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
        onOpen={(id) => go({ page: 'editor', projectId: id })}
        onUpload={(file) => void load(file)}
        onSample={() => void loadSample()}
        onDelete={(id) => void removeProject(id)}
        uploading={loading}
        progress={uploadShare}
        error={error}
      />
    )
  }
  if (route.page === 'voices') return <VoicesPage me={me} />
  if (route.page === 'usage') return <UsagePage me={me} />
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
        ) : <><Wave busy /><span className="text-muted-foreground">Opening {route.projectId}…</span></>}
      </div>
    )
  }

  const speakers = project.speakers ?? []
  // 20f: the spoken lines only; added lines and proposals are rows of their own in LineDoc.
  const statements: Statement[] = project.statements ?? []

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
  const captionRuns = captionAt(sourceClock, statements, approved, [...pendingLines, ...takesInHand], transcript, rendered !== null && view === 'original')
  // A take playing in place with word times (the polish pass): its words, lit as they are said.
  const spoken = playingTake && playingCandidate.current?.candidate_id === playingTake && playingCandidate.current.words?.length
    ? takeCaption(playingCandidate.current.words, currentTime - playingCandidate.current.plan.selection.start)
    : null
  const caption = spoken
    ? spoken.map((w, k) => <Fragment key={k}>{k > 0 && ' '}<ins data-said={w.said || undefined}>{w.text}</ins></Fragment>)
    : captionRuns?.map((r, k) => <Fragment key={k}>{k > 0 && ' '}{r.kind === 'ins' ? <ins>{r.text}</ins> : r.text}</Fragment>)

  const views = [
    ...(rendered ? [['final', 'Final'] as const] : []),
    ...(readyItems.length > 0 ? [['proposals', 'With proposals'] as const] : []),
    ['original', 'Original'] as const,
  ]
  const badge = views.length > 1 ? views.find(([v]) => v === view)?.[1] : undefined
  const scanning = turnBusy ? (turnStep ?? 'Voltage is working') : readingBusy ? 'Voltage is reading the clip' : null
  const spent = usage?.spent_usd ?? 0
  const ceiling = usage?.ceiling_usd ?? mayDo.ceiling_usd
  const sight = reading?.sight ?? null
  const place = sight ? (sight.place_confirmed ?? sight.place_guess) : null

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground max-[960px]:h-auto max-[960px]:min-h-dvh">
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to the transcript</a>
      {/* Volt: the editor's header — the wordmark, the file, the play switch, the autonomy, the spend, Export, the account. */}
      <header className="flex min-h-[62px] flex-wrap items-center gap-x-4 gap-y-2 border-b-[1.5px] border-foreground bg-card px-4 py-2 sm:px-6">
        <Wordmark />
        <span className="text-faint max-sm:hidden" aria-hidden="true">/</span>
        <h1 className="disp m-0 min-w-0 max-w-[28ch] truncate text-[15px] font-semibold" title={project.filename}>{project.filename}</h1>
        <span className="tag text-faint">{timecode(project.duration)}{speakers.length > 0 ? ` · ${speakers.length} ${speakers.length === 1 ? 'voice' : 'voices'}` : ''}</span>
        {views.length > 1 && (
          <div className="segs" role="group" aria-label="Play">
            {views.map(([v, label]) => (
              <button key={v} type="button" className="seg" aria-pressed={view === v} onClick={() => { setView(v); setCurrentTime(0); if (v === 'proposals') void ensurePreview() }}>
                {v === 'proposals' && !previewReady && previewing ? `${label}…` : label}
              </button>
            ))}
          </div>
        )}
        <span className="flex-1" />
        <button type="button" className="act" onClick={() => setMayDoOpen(true)} aria-haspopup="dialog" aria-label={`${autonomy === 'ask' ? 'Check with me' : 'Just do it'}. What Voltage may do`}>
          <span className="tag">{autonomy === 'ask' ? 'Check with me' : 'Just do it'}</span>
          <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
        <a className="tnum flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-foreground no-underline hover:bg-sunk" href={hrefFor({ page: 'usage' })} aria-label={`Spent $${spent.toFixed(2)} of $${ceiling} on this project. Usage`} data-testid="spend">
          ${spent.toFixed(2)}
          <span className="h-2 w-12 overflow-hidden rounded-sm bg-line" aria-hidden="true"><span className="block h-full bg-foreground" style={{ width: `${Math.min(100, ceiling > 0 ? (spent / ceiling) * 100 : 0)}%` }} /></span>
          <span className="text-faint">${Number.isInteger(ceiling) ? ceiling : ceiling.toFixed(2)}</span>
        </a>
        <a className={cn('btn ink sm', exporting && 'opacity-70')} href={hrefFor({ page: 'export', projectId: project.project_id })} aria-busy={exporting || undefined}>
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
              src={shown ? shown.url : artifactUrl(project.project_id, project.media.sha256)}
              duration={shown ? shown.duration : project.duration}
              currentTime={currentTime}
              onSeek={setCurrentTime}
              onTimeUpdate={setCurrentTime}
              seekRequest={seekRequest}
              caption={caption}
              muted={playingTake !== null && playingMix === 'replace'}
              badge={badge}
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
                  speakers={speakers}
                  revisions={approved}
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
                  <Timeline key={project.project_id} words={transcript} duration={project.duration} selection={selection} currentTime={sourceClock} onSelect={setSelection} />
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
          </div>
        </main>

        {/* Voltage: black in both themes. */}
        <aside className="pane flex min-h-0 w-[400px] shrink-0 flex-col max-[960px]:min-h-[60dvh] max-[960px]:w-auto" aria-label="Voltage" aria-busy={turnBusy || undefined}>
          <VoltagePane
            messages={messages}
            projectId={project.project_id}
            state={stateWord}
            busy={turnBusy || readingBusy}
            need={clarifying}
            engine={engine}
            cap={`Turn cap $${mayDo.turn_usd.toFixed(2)}`}
            question={clarifying ? plan?.question ?? null : null}
            onAnswer={(o) => void clarify(o)}
            onSubmit={submitComposer}
            inputRef={composerRef}
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
                  <a className="btn volt sm" href={hrefFor({ page: 'export', projectId: project.project_id })}>Export →</a>
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
    </div>
  )
}
