import { useCallback, useEffect, useRef, useState } from 'react'
import { ConsentGate } from './components/ConsentGate'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { CandidateCard } from './components/CandidateCard'
import { QuestionCard } from './components/QuestionCard'
import { ExportBar } from './components/ExportBar'
import { ProjectList } from './components/ProjectList'
import { SpendMeter } from './components/SpendMeter'
import { TranscriptDoc } from './components/TranscriptDoc'
import type { LineChange } from './components/TranscriptDoc'
import { VoicePicker } from './components/VoicePicker'
import { SpeakersBar } from './components/SpeakersBar'
import { clock } from './transcript/format'
import { speakerSlot } from './transcript/speakers'
import {
  createProject, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject, getUsage, listVoices, updateSpeaker, detectSpeakers,
  revertEdit, updateSettings, rewordLine,
} from './api'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage, Question, QuestionOption,
  Fit, Mix, Insert, ProjectSummary, Usage, Statement, Voice, Revision, LongLines, LineStatus,
} from './types'
import { renderTime, sourceTime } from './timeline/selection'
import styles from './App.module.css'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'
// Until the voice list loads: the server's configured default voice.
const DEFAULT_VOICE = 'speaker-1'

/** An answer to a question: the line already read, and the choices so far. */
interface Answer { text: string; fit?: Fit; mix?: Mix; on_long?: LongLines }

type Stage = 'consent' | 'load' | 'editor'

/** The chat's voice, or the speaker's own, named for a take. */
const voiceName = (voices: Voice[], id: string) => voices.find((v) => v.voice_id === id)?.name

export default function App() {
  const [stage, setStage] = useState<Stage>('consent')
  // Tracked explicitly rather than inferred from the stage, so what we send is
  // what the user actually confirmed.
  const [consented, setConsented] = useState(false)
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
  // The latest render of the approved edits, and which version the player shows.
  const [rendered, setRendered] = useState<{ url: string; duration: number } | null>(null)
  const [view, setView] = useState<'original' | 'edited'>('original')
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState(DEFAULT_VOICE)
  const [seekRequest, setSeekRequest] = useState<{ time: number; id: number } | null>(null)
  const [detecting, setDetecting] = useState(false)
  // Approved edits still in force, shown as tracked changes in the transcript.
  const [approved, setApproved] = useState<Revision[]>([])
  // How this project places a line that runs long; remembered on the server.
  const [longLines, setLongLines] = useState<LongLines>('pause')
  const previewToken = useRef(0)

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

  // A reload keeps you in the project you had open: its id is the URL hash.
  // Its consent was recorded when it was uploaded.
  useEffect(() => {
    const id = window.location.hash.slice(1)
    if (/^p\d+$/.test(id)) void openProject(id)
    // Only on first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
  }

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

  const takeIn = (loaded: Project) => {
    setProject(loaded)
    setTranscript(loaded.transcript)
    setLongLines(loaded.settings?.long_lines ?? 'pause')
    setStage('editor')
    window.location.hash = loaded.project_id
  }

  const load = async (file: File) => {
    setLoading(true)
    setError(null)
    try {
      takeIn(await createProject(file, consented))
    } catch (e) {
      // The backend's rejection reason is the useful part — show it verbatim.
      setError(e instanceof ApiError ? e.message : 'Could not upload that video.')
    } finally {
      setLoading(false)
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

  const runPreview = async (
    prompt: string,
    answer?: Answer,
    at: Selection | null = selection,
    shown: string = prompt,
    voice: string = voiceId,
  ) => {
    if (!projectId || !at) return
    say({ role: 'user', text: shown })
    setCandidate(null)
    setQuestion(null)
    setError(null)
    setGenerating(true)
    setWorking(at)
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
        onUpdate: (j) => setProgress({ value: j.progress, step: j.step }),
      })
      if (superseded()) return

      const result = finished.result
      if (finished.status === 'failed' || !result) {
        setError(finished.error ?? 'Preview failed. Try again.')
        return
      }
      if (result.type === 'reply') {
        say({ role: 'assistant', text: result.text })
        return
      }
      if (result.type === 'question') {
        say({ role: 'assistant', text: result.question })
        setQuestion({ question: result, prompt, selection: at })
        return
      }
      setSelection(result.plan.selection) // the backend's snapped range
      setCandidate(result)
    } catch (e) {
      if (e instanceof PollCancelled) return
      setError(e instanceof ApiError ? e.message : 'Preview failed. Try again.')
    } finally {
      if (!superseded()) {
        setGenerating(false)
        setWorking(null)
        setProgress(null)
      }
      void refreshUsage(projectId)
    }
  }

  /** A line rewritten in the transcript: an edit of its span with the new
   *  wording given directly — there is nothing for Claude to interpret. */
  const editStatement = (s: Statement, change: LineChange) => {
    const span = { start: s.start, end: s.end }
    setSelection(span)
    void runPreview(
      `Replace this line with "${change.text}"`,
      { text: change.text, mix: 'replace', on_long: change.onLong },
      span,
      `“${s.text}” → “${change.text}”`,
      change.voiceId ?? voiceId,
    )
  }

  /** Remember, for this project, what to do when a line runs long. */
  const rememberLongLines = async (value: LongLines) => {
    if (!projectId || value === longLines) return
    setLongLines(value)
    try {
      await updateSettings(projectId, { long_lines: value })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save that setting.')
    }
  }

  /** Ask Claude for a wording of a line; the suggestion goes in the box. */
  const reword = async (s: Statement, draft: string): Promise<string | null> => {
    if (!projectId) return null
    setError(null)
    try {
      const r = await rewordLine(projectId, { start: s.start, end: s.end, draft })
      return r.text
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not get a wording.')
      return null
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
    const remaining = approved.filter((r) => r.edit_id !== editId)
    setApproved(remaining)
    setDownload(null)
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
    }
  }

  const openProject = async (id: string) => {
    clearEditor()
    setLoading(true)
    try {
      const opened = await getProject(id)
      takeIn(opened)
      setMessages(opened.messages)
      const live = opened.edits.filter((e) => !e.reverted)
      setApproved(live.map((e) => ({
        edit_id: e.edit_id, start: e.selection.start, end: e.selection.end, text: e.new_text, mix: e.mix,
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

  if (stage === 'consent') {
    return (
      <ConsentGate
        onConfirm={() => {
          setConsented(true)
          setStage('load')
        }}
      />
    )
  }
  if (stage === 'load' || !project) {
    return (
      <LoadScreen
        onLoad={load}
        onLoadSample={loadSample}
        loading={loading}
        error={error}
      >
        <ProjectList projects={projects} onOpen={(id) => void openProject(id)} onDelete={(id) => void removeProject(id)} />
      </LoadScreen>
    )
  }

  const showEdited = view === 'edited' && rendered !== null
  const speakers = project.speakers ?? []
  const statements = project.statements ?? []
  const leave = () => {
    clearEditor()
    window.location.hash = ''
    // Uploading again needs the rights confirmed in this session.
    setStage(consented ? 'load' : 'consent')
  }

  // Where the editor stands on a line: working on it, a take ready, or a
  // question waiting for you.
  const pending: { selection: Selection; status: LineStatus } | null =
    generating && working ? { selection: working, status: 'working' }
    : question ? { selection: question.selection, status: 'needs-you' }
    : candidate ? { selection: candidate.plan.selection, status: 'ready' }
    : null

  // The take's own details: whose line, in which voice, and whether it ran on.
  const takeSpeakerLabel = candidate
    ? statements.find((s) => s.start < candidate.plan.selection.end && candidate.plan.selection.start < s.end)?.speaker
    : null
  const takeSpeaker = speakers.find((s) => s.label === takeSpeakerLabel)
  const takeVoice = candidate ? voiceName(voices, candidate.plan.voice_profile_id) : undefined
  const overrun = candidate && asked ? candidate.plan.selection.end - asked.end : 0
  const ranOn = candidate?.plan.mix !== 'concatenate' && overrun > 0.01

  const sourceClock = showEdited ? sourceTime(currentTime, inserts) : currentTime
  const marks = approved.map((r) => (showEdited ? renderTime(r.start, inserts) : r.start))

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <button className={styles.back} onClick={leave}>← Projects</button>
        <span className={styles.slash}>/</span>
        <span className={styles.filename} title={project.filename}>{project.filename}</span>
        <span className={styles.meta}>
          {project.duration.toFixed(1)} s{speakers.length > 0 && `, ${speakers.length} ${speakers.length === 1 ? 'speaker' : 'speakers'}`}
        </span>
        <span className={styles.spacer} />
        <SpendMeter usage={usage} />
        <ExportBar segments={segments} inserts={inserts} onExport={() => void runExport()} download={download} />
      </header>

      <main className={styles.main}>
        <Player
          src={showEdited ? rendered.url : artifactUrl(project.project_id, project.media.sha256)}
          duration={showEdited ? rendered.duration : project.duration}
          currentTime={currentTime}
          onSeek={setCurrentTime}
          onTimeUpdate={setCurrentTime}
          seekRequest={seekRequest}
          marks={marks}
        >
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
        <Timeline
          key={project.project_id}
          words={transcript}
          duration={project.duration}
          selection={selection}
          currentTime={sourceClock}
          onSelect={setSelection}
        />
        {error && <div className={styles.error} role="alert">{error}</div>}
        <SpeakersBar
          speakers={speakers}
          voices={voices}
          hasSpeech={transcript.length > 0}
          detecting={detecting}
          onDetect={() => void findSpeakers()}
          onRename={(label, name) => void changeSpeaker(label, { name })}
          onVoice={(label, id) => void changeSpeaker(label, id ? { voice_id: id } : { clear_voice: true })}
        />
        <TranscriptDoc
          statements={statements}
          words={transcript}
          speakers={speakers}
          voices={voices}
          revisions={approved}
          selection={selection}
          currentTime={sourceClock}
          pending={pending}
          longLines={longLines}
          disabled={generating}
          onSeek={seekToStatement}
          onEdit={editStatement}
          onRevert={(id) => void revert(id)}
          onReword={reword}
          onLongLinesChange={(v) => void rememberLongLines(v)}
        />
      </main>

      <aside className={styles.panel}>
        <ChatPanel
          messages={messages}
          canSubmit={selection !== null}
          onSubmit={(p) => void runPreview(p)}
          toolbar={<VoicePicker voices={voices} value={voiceId} onChange={setVoiceId} />}
          header={
            <div className={styles.panelHead}>
              <span className={styles.panelTitle}>Voltage</span>
              <span className={styles.panelNote}>
                {selection ? `Talking about ${clock(selection.start)}` : 'Pick a line to talk about it'}
              </span>
            </div>
          }
        >
          {generating && (
            <div className={styles.generating} data-testid="generating">
              <div className={styles.generatingStep}>
                <span className={styles.spinner} aria-hidden="true" />
                {progress?.step ?? 'Queued'}
              </div>
              <div className={styles.progressTrack}>
                <div
                  data-testid="progress-bar"
                  className={styles.progressFill}
                  style={{ width: `${Math.round((progress?.value ?? 0) * 100)}%` }}
                />
              </div>
            </div>
          )}
          {question && <QuestionCard question={question.question} onChoose={answer} />}
          {candidate && (
            <>
              <CandidateCard
                candidate={candidate}
                onApprove={() => void approve()}
                onApproveAnyway={() => void approve(true)}
                onTryAgain={() => { setCandidate(null); setAsked(null) }}
                projectId={project.project_id}
                label={`The change at ${clock(candidate.plan.selection.start)}${takeVoice ? `, ${takeVoice}'s voice` : ''}`}
                speaker={takeSpeaker ? { name: takeSpeaker.name, slot: speakerSlot(speakers, takeSpeaker.label) } : null}
                note={ranOn ? `Ran ${overrun.toFixed(1)} s into the pause after it` : null}
              />
              {ranOn && longLines === 'pause' && (
                <div className={styles.remembered}>
                  Longer lines run into the pause after them in this project.{' '}
                  <button onClick={() => void rememberLongLines('ask')}>Ask me each time instead</button>
                </div>
              )}
            </>
          )}
        </ChatPanel>
      </aside>
    </div>
  )
}
