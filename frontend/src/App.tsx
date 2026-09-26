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
import { TranscriptPanel } from './components/TranscriptPanel'
import { VoicePicker } from './components/VoicePicker'
import { SpeakersBar } from './components/SpeakersBar'
import {
  createProject, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject, getUsage, listVoices, updateSpeaker, detectSpeakers,
} from './api'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage, Question, QuestionOption,
  Fit, Mix, Insert, ProjectSummary, Usage, Statement, Voice,
} from './types'
import { renderTime, sourceTime } from './timeline/selection'
import styles from './App.module.css'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'
// Until the voice list loads: the server's configured default voice.
const DEFAULT_VOICE = 'speaker-1'

/** An answer to a question: the line already read, and the choices so far. */
interface Answer { text: string; fit?: Fit; mix?: Mix }

type Stage = 'consent' | 'load' | 'editor'

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
  // The open question, with the request it is about — answering re-sends that
  // request for the same selection, plus the choice.
  const [question, setQuestion] = useState<
    { question: Question; prompt: string; selection: Selection } | null
  >(null)
  const [generating, setGenerating] = useState(false)
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

  /** Back to a blank editor state, e.g. before opening another project. */
  const clearEditor = () => {
    previewToken.current += 1 // abandon any poll in flight
    setProject(null)
    setTranscript([])
    setSelection(null)
    setCurrentTime(0)
    setMessages([])
    setCandidate(null)
    setQuestion(null)
    setGenerating(false)
    setProgress(null)
    setSegments([])
    setInserts([])
    setDownload(null)
    setRendered(null)
    setView('original')
    setError(null)
    setUsage(null)
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

  const load = async (file: File) => {
    setLoading(true)
    setError(null)
    try {
      const loaded = await createProject(file, consented)
      setProject(loaded)
      setTranscript(loaded.transcript)
      setStage('editor')
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
  ) => {
    if (!projectId || !at) return
    say({ role: 'user', text: shown })
    setCandidate(null)
    setQuestion(null)
    setError(null)
    setGenerating(true)
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
        voice_profile_id: voiceId,
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
        setProgress(null)
      }
      void refreshUsage(projectId)
    }
  }

  /** A statement rewritten in the transcript: an edit of its span with the
   *  new wording given directly — there is nothing for Claude to interpret. */
  const editStatement = (s: Statement, text: string) => {
    const span = { start: s.start, end: s.end }
    setSelection(span)
    void runPreview(`Replace this line with "${text}"`, { text, mix: 'replace' }, span,
      `“${s.text}” → “${text}”`)
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
      await approveEdit(projectId, candidate.candidate_id, override)
      setCandidate(null)
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
      setProject(opened)
      setTranscript(opened.transcript)
      setMessages(opened.messages)
      setStage('editor')
      // Approved edits are rendered again, so Play hears them straight away.
      if (opened.edits.length > 0 && await runExport(opened.project_id, opened.filename)) {
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

  return (
    <div className={styles.app}>
      <div className={styles.left}>
        <div className={styles.topbar}>
          <button className={styles.back} onClick={() => { clearEditor(); setStage('load') }}>
            ← Projects
          </button>
          <span className={styles.filename}>{project.filename}</span>
        </div>
        <Player
          src={showEdited ? rendered.url : artifactUrl(project.project_id, project.media.sha256)}
          duration={showEdited ? rendered.duration : project.duration}
          currentTime={currentTime}
          onSeek={setCurrentTime}
          onTimeUpdate={setCurrentTime}
          seekRequest={seekRequest}
        />
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
        <Timeline
          key={project.project_id}
          words={transcript}
          duration={project.duration}
          selection={selection}
          currentTime={showEdited ? sourceTime(currentTime, inserts) : currentTime}
          onSelect={setSelection}
        />
        <SpeakersBar
          speakers={project.speakers ?? []}
          voices={voices}
          hasSpeech={transcript.length > 0}
          detecting={detecting}
          onDetect={() => void findSpeakers()}
          onRename={(label, name) => void changeSpeaker(label, { name })}
          onVoice={(label, voiceId) => void changeSpeaker(
            label, voiceId ? { voice_id: voiceId } : { clear_voice: true })}
        />
        <TranscriptPanel
          speakerNames={Object.fromEntries((project.speakers ?? []).map((sp) => [sp.label, sp.name]))}
          statements={project.statements ?? []}
          currentTime={showEdited ? sourceTime(currentTime, inserts) : currentTime}
          disabled={generating}
          onSeek={seekToStatement}
          onEdit={editStatement}
        />
        <ExportBar segments={segments} inserts={inserts} onExport={() => void runExport()} download={download} />
        <SpendMeter usage={usage} />
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.right}>
        <ChatPanel
          messages={messages}
          canSubmit={selection !== null}
          onSubmit={(p) => void runPreview(p)}
          toolbar={<VoicePicker voices={voices} value={voiceId} onChange={setVoiceId} />}
        >
          {generating && (
            <div className={styles.generating} data-testid="generating">
              <div className={styles.generatingStep}>{progress?.step ?? 'Queued'}</div>
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
            <CandidateCard
              candidate={candidate}
              onApprove={() => void approve()}
              onApproveAnyway={() => void approve(true)}
              onTryAgain={() => setCandidate(null)}
              projectId={project.project_id}
            />
          )}
        </ChatPanel>
      </div>
    </div>
  )
}
