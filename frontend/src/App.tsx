import { useState } from 'react'
import { ConsentGate } from './components/ConsentGate'
import { LoadScreen } from './components/LoadScreen'
import { Player } from './components/Player'
import { Timeline } from './components/Timeline'
import { ChatPanel } from './components/ChatPanel'
import { CandidateCard } from './components/CandidateCard'
import { ExportBar } from './components/ExportBar'
import { createProject, previewEdit, approveEdit, exportProject, ApiError } from './api'
import type { Word, Selection, Candidate, Segment } from './types'
import styles from './App.module.css'

const SAMPLE = { filename: 'sample-ad.mp4', duration: 2.3, src: '/sample-ad.mp4' }
const VOICE = 'speaker-1'

type Stage = 'consent' | 'load' | 'editor'

export default function App() {
  const [stage, setStage] = useState<Stage>('consent')
  const [loading, setLoading] = useState(false)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<Word[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [messages, setMessages] = useState<string[]>([])
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [generating, setGenerating] = useState(false)
  const [lastPrompt, setLastPrompt] = useState('')
  const [segments, setSegments] = useState<Segment[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const project = await createProject(SAMPLE.filename, SAMPLE.duration)
      setProjectId(project.project_id)
      setTranscript(project.transcript)
      setStage('editor')
    } catch {
      setError('Could not load the project.')
    } finally {
      setLoading(false)
    }
  }

  const runPreview = async (prompt: string) => {
    if (!projectId || !selection) return
    setMessages((m) => [...m, prompt])
    setLastPrompt(prompt)
    setCandidate(null)
    setError(null)
    setGenerating(true)
    try {
      const c = await previewEdit(projectId, {
        prompt,
        start: selection.start,
        end: selection.end,
        voice_profile_id: VOICE,
      })
      setSelection(c.plan.selection) // reflect the backend's snapped range
      setCandidate(c)
    } catch {
      setError('Preview failed. Try again.')
    } finally {
      setGenerating(false)
    }
  }

  const approve = async () => {
    if (!projectId || !candidate) return
    setError(null)
    try {
      await approveEdit(projectId, {
        prompt: lastPrompt,
        start: candidate.plan.selection.start,
        end: candidate.plan.selection.end,
        voice_profile_id: VOICE,
      })
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

  if (stage === 'consent') return <ConsentGate onConfirm={() => setStage('load')} />
  if (stage === 'load') return <LoadScreen onLoad={load} loading={loading} />

  return (
    <div className={styles.app}>
      <div className={styles.left}>
        <Player
          src={SAMPLE.src}
          duration={SAMPLE.duration}
          currentTime={currentTime}
          onSeek={setCurrentTime}
        />
        <Timeline
          words={transcript}
          duration={SAMPLE.duration}
          selection={selection}
          currentTime={currentTime}
          onSelect={setSelection}
        />
        <ExportBar segments={segments} onExport={runExport} />
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.right}>
        <ChatPanel messages={messages} canSubmit={selection !== null} onSubmit={runPreview}>
          {generating && <div className={styles.generating}>Generating candidate…</div>}
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
