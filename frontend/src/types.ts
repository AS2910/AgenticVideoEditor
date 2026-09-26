export interface Word { text: string; start: number; end: number }
/** A sentence as spoken, with punctuation — edited from the transcript panel. */
export interface Statement { text: string; start: number; end: number }

/** A voice a new line can be spoken in. */
export interface Voice {
  voice_id: string
  name: string
  description: string
  gender: string | null
  accent: string | null
  age: string | null
}
export interface Selection { start: number; end: number }

/** A score is null when it cannot be measured yet (no voice clone, no real
 *  lip-sync). `measured` names the scores taken from the media itself; any
 *  other number is simulated by the offline mock engine. */
export interface ContinuityReport {
  voice_match: number | null
  prosody: number | null
  audio_integration: number | null
  lip_sync: number | null
  passed: boolean
  warnings: string[]
  measured: string[]
}

export type Fit = 'start' | 'stretch'
export type Mix = 'replace' | 'layer' | 'concatenate'

export interface EditPlan {
  selection: Selection
  new_text: string
  voice_profile_id: string
  fit?: Fit | null
  mix?: Mix
}

/** A real media file held by the backend, addressed by the hash of its bytes. */
export interface MediaArtifact {
  kind: 'audio' | 'video'
  sha256: string
  duration: number
  container: string
}

export interface Candidate {
  type?: 'candidate'
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
  /** Absent from responses of servers before Phase 10. */
  statements?: Statement[]
}

/** What a project has spent. USD is an estimate from list prices. */
export interface Usage {
  spent_usd: number
  ceiling_usd: number
  voice_characters: number
  voice_characters_ceiling: number
  lines: { vendor: string; what: string; unit: string; units: number; usd: number; calls: number }[]
}

/** A row of the start screen's project list. */
export interface ProjectSummary {
  project_id: string
  filename: string
  duration: number
  created_at: string
  edits: number
}

export interface ApprovedEditSummary {
  edit_id: string
  candidate_id: string
  new_text: string
  selection: Selection
  mix: Mix
  overridden: boolean
}

/** A reopened project: the upload plus what has been done to it. */
export interface ProjectDetail extends Project {
  edits: ApprovedEditSummary[]
  messages: ChatMessage[]
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

/** A line added after a point in the video: the frame there is held while
 *  it plays, so the export is longer than the source. */
export interface Insert { at: number; duration: number; artifact: MediaArtifact }

/** `render` is the finished MP4, stored like any other artifact. */
export interface ExportManifest { segments: Segment[]; render: MediaArtifact; inserts?: Insert[] }

export interface ChatMessage { role: 'user' | 'assistant'; text: string }

export interface EditRequest {
  prompt: string
  start: number
  end: number
  voice_profile_id: string
  /** Set when answering a question: the line already read from the prompt. */
  text?: string
  fit?: Fit
  mix?: Mix
  /** What the chat shows for this turn when it isn't the prompt — the label
   *  of an option picked in answer to a question. */
  display?: string
}

export interface QuestionOption {
  label: string
  fit: Fit | null
  mix: Mix | null
  /** Shown with the option, e.g. a stretch far outside natural speech. */
  warning: string | null
}

/** Asked instead of refusing an edit: how to mix, or how to fit the line. */
export interface Question {
  type: 'question'
  question: string
  text: string
  mix: Mix | null
  options: QuestionOption[]
}

/** A chat answer instead of an edit — e.g. a request the editor can't do. */
export interface Reply { type: 'reply'; text: string }

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
  result: Candidate | Question | Reply | null
  error: string | null
}
