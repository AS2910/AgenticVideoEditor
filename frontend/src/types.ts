export interface Word { text: string; start: number; end: number }
/** A sentence as spoken, with punctuation — edited from the transcript panel. */
export interface Statement { text: string; start: number; end: number; speaker?: string | null }

/** An approved edit as the transcript shows it: the new words over a span,
 *  as inline tracked changes. `edit_id` is what Revert names. */
export interface Revision { edit_id?: string; start: number; end: number; text: string; mix: Mix }

/** What happens when a new line runs longer than the words it replaces:
 *  run into the pause after them (when there is room), speed it up, or ask. */
export type LongLines = 'pause' | 'shorten' | 'stretch' | 'ask'

/** How much Voltage does on its own: show the plan and wait for Run (the
 *  controlled default), or voice it straight away. */
export type Autonomy = 'ask' | 'draft'

/** Per-project preferences, remembered on the server. */
export interface ProjectSettings { long_lines: LongLines; autonomy: Autonomy }

/** Where a plan item stands. */
export type ItemStatus =
  | 'planned' | 'working' | 'ready' | 'needs-you' | 'failed' | 'approved' | 'suggested' | 'dismissed'

/** One change in the agent's plan: a line and the new words for it. */
export interface PlanItem {
  item_id: string
  selection: Selection
  old_text: string
  new_text: string
  speaker: string | null
  mix: Mix
  delivery?: string | null
  reason: string
  /** A suggestion is a change the goal implied but did not name; it joins
   *  the plan only when added. */
  kind: 'planned' | 'suggestion'
  enabled: boolean
  status: ItemStatus
  fit: Fit | null
  candidate: Candidate | null
  edit_id: string | null
  question: Question | null
  error: string | null
  note: string | null
  /** What is happening to it right now, in words, while the plan runs. */
  progress: string | null
}

/** One thing the planner wants to know first, with its own guess. */
export interface PlanQuestion { text: string; options: string[]; guess: string | null }

export interface PlanLogEntry { at: string; text: string; detail: string }

/** What the agent proposes for the whole video, and how far it has got. */
export interface Plan {
  type?: 'plan'
  plan_id: string
  goal: string
  summary: string
  mode: Autonomy
  status: 'clarifying' | 'proposed' | 'running' | 'done'
  created_at: string
  estimate: { items: number; voice_characters: number; usd: number; seconds: number }
  /** What the planner noticed while reading, in order. */
  findings: string[]
  question: PlanQuestion | null
  /** What this plan has cost so far, estimated. */
  spend_usd: number
  log: PlanLogEntry[]
  items: PlanItem[]
  /** Under "draft": the job already voicing the plan. */
  job_id?: string
}

/** Where a line stands while the editor works on it. */
export type LineStatus = 'working' | 'ready' | 'needs-you'

/** A diarized speaker: what to call them, and the voice their new lines are
 *  spoken in (null = the chat's voice). */
export interface Speaker { label: string; name: string; voice_id: string | null }

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
export type Mix = 'replace' | 'layer' | 'concatenate' | 'over' | 'remove'

/** How a line is said (UX-1). */
export type Delivery = 'warmer' | 'more excited' | 'calmer' | 'slower' | 'firmer' | string

export interface EditPlan {
  selection: Selection
  new_text: string
  voice_profile_id: string
  fit?: Fit | null
  mix?: Mix
  delivery?: string | null
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
  /** What was done to make the take fit its slot, in words (Phase 14). */
  fit_notes?: string[]
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
  /** Absent from responses of servers before Phase 11. */
  speakers?: Speaker[]
  /** Absent from responses of servers before Phase 12. */
  settings?: ProjectSettings
  /** The latest plan, if the agent has made one (Phase 13). */
  plan?: Plan | null
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
  /** Undone after approval; the render skips it. */
  reverted?: boolean
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

/** A wording Claude suggests for a line; nothing is spoken yet. */
export interface Rewording { text: string; selection: Selection }

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
  /** How it is said (UX-1). */
  delivery?: string
  /** What the chat shows for this turn when it isn't the prompt — the label
   *  of an option picked in answer to a question. */
  display?: string
  /** For this edit only: how a line that runs long is placed. Unset = the
   *  project's setting. */
  on_long?: LongLines
}

export interface QuestionOption {
  label: string
  fit: Fit | null
  mix: Mix | null
  /** The agent's own fix: a different wording to use instead. */
  text?: string | null
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
  result: Candidate | Question | Reply | Plan | null
  error: string | null
}
