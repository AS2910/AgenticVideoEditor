export interface Word { text: string; start: number; end: number }
export interface Selection { start: number; end: number }

export interface ContinuityReport {
  voice_match: number
  prosody: number
  audio_integration: number
  lip_sync: number
  passed: boolean
  warnings: string[]
}

export interface EditPlan {
  selection: Selection
  new_text: string
  voice_profile_id: string
}

/** A real media file held by the backend, addressed by the hash of its bytes. */
export interface MediaArtifact {
  kind: 'audio' | 'video'
  sha256: string
  duration: number
  container: string
}

export interface Candidate {
  candidate_id: string
  plan: EditPlan
  audio: MediaArtifact
  frames: MediaArtifact
  continuity: ContinuityReport
}

/** Recorded when the uploader confirms rights; null until they do. */
export interface ConsentRecord { granted_at: string }

export interface Project {
  project_id: string
  filename: string
  /** Measured server-side by ffprobe — the client never asserts this. */
  duration: number
  media: MediaArtifact
  consent: ConsentRecord | null
  transcript: Word[]
}

export interface ApprovedResult {
  edit_id: string
  candidate_id: string
  continuity: ContinuityReport
}

export interface Segment {
  start: number
  end: number
  kind: 'original' | 'edited'
  ref: string
  artifact: MediaArtifact | null
}

export interface ExportManifest { segments: Segment[] }

export interface EditRequest {
  prompt: string
  start: number
  end: number
  voice_profile_id: string
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

/** Generation runs server-side and is polled; it takes minutes once lip-sync
 *  is a real vendor. */
export interface Job {
  job_id: string
  kind: string
  project_id: string
  status: JobStatus
  progress: number   // 0–1
  step: string       // human-readable, shown while waiting
  attempts: number
  result: Candidate | null
  error: string | null
}
