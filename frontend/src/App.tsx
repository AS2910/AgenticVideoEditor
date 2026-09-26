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
import {
  createProject, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError, listProjects, getProject, deleteProject,
} from './api'
import type {
  Word, Selection, Candidate, Segment, Project, ChatMessage, Question, QuestionOption,
  Fit, Mix, Insert, ProjectSummary,
} from './types'
import { sourceTime } from './timeline/selection'
import styles from './App.module.css'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'
const VOICE = 'speaker-1'

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
  }

  const projectId = project?.project_id ?? null

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
        voice_profile_id: VOICE,
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
    }
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
          words={transcript}
          duration={project.duration}
          selection={selection}
          currentTime={showEdited ? sourceTime(currentTime, inserts) : currentTime}
          onSelect={setSelection}
        />
        <ExportBar segments={segments} inserts={inserts} onExport={() => void runExport()} download={download} />
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.right}>
        <ChatPanel messages={messages} canSubmit={selection !== null} onSubmit={(p) => void runPreview(p)}>
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
