import { useRef, useState } from 'react'
import { ConsentGate } from './components/ConsentGate'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { CandidateCard } from './components/CandidateCard'
import { ExportBar } from './components/ExportBar'
import {
  createProject, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError,
} from './api'
import type { Word, Selection, Candidate, Segment, Project } from './types'
import styles from './App.module.css'

/** Bundled demo clip, uploaded through the same path as any other file. */
const SAMPLE_URL = '/sample-ad.mp4'
const VOICE = 'speaker-1'

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
  const [messages, setMessages] = useState<string[]>([])
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState<{ value: number; step: string } | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [error, setError] = useState<string | null>(null)
  const previewToken = useRef(0)

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

  const runPreview = async (prompt: string) => {
    if (!projectId || !selection) return
    setMessages((m) => [...m, prompt])
    setCandidate(null)
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
        start: selection.start,
        end: selection.end,
        voice_profile_id: VOICE,
      })
      const finished = await pollJob(job.job_id, {
        shouldStop: superseded,
        onUpdate: (j) => setProgress({ value: j.progress, step: j.step }),
      })
      if (superseded()) return

      if (finished.status === 'failed' || !finished.result) {
        setError(finished.error ?? 'Preview failed. Try again.')
        return
      }
      setSelection(finished.result.plan.selection) // the backend's snapped range
      setCandidate(finished.result)
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

  const approve = async () => {
    if (!projectId || !candidate) return
    setError(null)
    try {
      await approveEdit(projectId, candidate.candidate_id)
      setCandidate(null)
    } catch (e) {
      // Never silently drop the candidate — leave it on screen to iterate on.
      if (e instanceof ApiError && e.status === 422) {
        setError('Continuity check failed — this edit cannot ship.')
      } else {
        setError('Approve failed.')
      }
    }
  }

  const runExport = async () => {
    if (!projectId) return
    setError(null)
    try {
      const manifest = await exportProject(projectId)
      setSegments(manifest.segments)
    } catch {
      setError('Export failed.')
    }
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
      />
    )
  }

  return (
    <div className={styles.app}>
      <div className={styles.left}>
        <Player
          src={artifactUrl(project.project_id, project.media.sha256)}
          duration={project.duration}
          currentTime={currentTime}
          onSeek={setCurrentTime}
        />
        <Timeline
          words={transcript}
          duration={project.duration}
          selection={selection}
          currentTime={currentTime}
          onSelect={setSelection}
        />
        <ExportBar segments={segments} onExport={runExport} />
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.right}>
        <ChatPanel messages={messages} canSubmit={selection !== null} onSubmit={runPreview}>
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
          {candidate && (
            <CandidateCard
              candidate={candidate}
              onApprove={approve}
              onTryAgain={() => setCandidate(null)}
            />
          )}
        </ChatPanel>
      </div>
    </div>
  )
}
