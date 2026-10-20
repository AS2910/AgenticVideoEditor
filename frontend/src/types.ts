export interface Word { text: string; start: number; end: number }
/** A sentence as spoken, with punctuation — edited from the transcript panel. */
export interface Statement { text: string; start: number; end: number; speaker?: string | null; /** UX-5: a voice-over placed by time on a clip with no speech. */ placed?: boolean }

/** An approved edit as the transcript shows it: the new words over a span,
 *  as inline tracked changes. `edit_id` is what Revert names. */
export interface Revision { edit_id?: string; start: number; end: number; text: string; mix: Mix; /** The other half of a shifted line. */ partner?: string | null; /** 2026-10-20: what it is in the mix, and the fine-tune on top, dB. */ role?: Role; offset_db?: number | null; /** Volt: who says it and whose voice, when known. */ speaker?: string | null; voice_profile_id?: string | null }

/** How much Voltage does on its own: show the plan and wait for your go (the
 *  controlled default), or voice it straight away. */
export type Autonomy = 'ask' | 'draft'

/** How hard Voltage thinks on a turn; the sheet "What Voltage may do" sets it. */
export type Effort = 'medium' | 'high' | 'xhigh'

/** Per-project preferences, remembered on the server. */
/** What Voltage may do on a project (20d): the autonomy, what one turn may spend, how hard it thinks; the ceiling is read-only. */
/** 2026-10-20: an added line is a Voice (words), a Bed (music, crowd, ambience: under the words, ducking) or an Effect. */
export type Role = 'voice' | 'bed' | 'effect'
export interface MixSettings { voice_default_lufs: number; bed_under_db: number; speech_clear_db: number; loudness: 'social' | 'general' }
/** What the mix did with one line: its level, how far a bed sits under the voices, whether a voice is heard. */
export interface MixLine {
  edit_id: string
  candidate_id: string
  item_id?: string | null
  role: Role
  start: number
  end: number
  gain_db: number | null
  level_lufs: number | null
  under_db: number | null
  alone: boolean
  ducks: boolean
  ratio_db: number | null
  covered_by: string | null
  flag: string | null
  /** A voice lifted over loud sound under it (a crowd, music) so it is heard, dB. */
  raised_db?: number | null
}
export interface MixReport { voice_lufs: number; lines: MixLine[]; loudness_lufs: number | null; true_peak_db: number | null }

export interface ProjectSettings { autonomy: Autonomy; turn_usd?: number; effort?: Effort; ceiling_usd?: number; /** Volt: which commits still ask under Just do it, and the model Voltage runs on. */ ask_before?: AskBefore; model?: string; /** The guided run's sample video: its turns replay a recording, free. */ tutorial?: boolean; /** 2026-10-20: the mix. */ mix?: MixSettings }

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
  /** p61: why the line could not be fitted, when it ran long for its gap. */
  fit_failure?: FitFailure | null
}

/** A line that ran long (p61): every figure measured or recorded by the server. */
export interface FitFailure {
  reason: 'too_long'
  /** Seconds the take needs, and seconds its gap has. */
  needs: number
  has: number
  /** The fit ladder's rungs, in the order they were tried. */
  tried: string[]
  syllables: number
  /** The syllables a shorter line should be written to. */
  budget: number
  /** What the take that ran long cost (a shorter one costs no more). */
  cost_usd: number
  text: string
  /** The paid take, fitted with the picture easing, kept for the user (no new cost). */
  eased_candidate_id: string | null
  ease_s: number | null
}

/** One thing the planner wants to know first, with its own guess. */
export interface PlanQuestion {
  text: string
  options: string[]
  guess: string | null
  /** Phase 20: a paid or committing step waits; the first option is the yes. */
  gate?: boolean
  /** Volt: what the waiting step would cost, and what the turn has left of its cap (`cap_usd`). */
  cost_usd?: number | null
  left_usd?: number | null
  cap_usd?: number | null
  /** Pane-render: the full sentence under each option's short label; null where there is none. */
  details?: (string | null)[] | null
  /** The turn's cap caused this question: the first option allows exactly `needed_usd` more (`POST /turns/allow-more`). */
  turn_cap?: { needed_usd: number; cap_usd: number } | null
  /** 2026-10-20: settled outside the chat (an item it was about was added, discarded or redone): why, and where. */
  resolved?: { why: string; by: 'editor' | 'chat'; at: string; answer?: string } | null
}

export interface PlanLogEntry { at: string; text: string; detail: string }

/** What the agent proposes for the whole video, and how far it has got. */
export interface Plan {
  type?: 'plan'
  plan_id: string
  goal: string
  summary: string
  mode: Autonomy
  status: 'clarifying' | 'proposed' | 'running' | 'stopping' | 'done'
  created_at: string
  estimate: { items: number; voice_characters: number; usd: number; seconds: number }
  /** What the planner noticed while reading, in order. */
  findings: string[]
  question: PlanQuestion | null
  /** UX-5: the brief so far, and how many questions may still come. */
  voice?: string | null
  /** 15e: the goal asked for a kind of voice and `voice` answers it — it then
   *  speaks every line not yet voiced; and one plain sentence on the choice. */
  voice_asked?: boolean
  voice_note?: string | null
  /** What this plan has cost so far, estimated. */
  spend_usd: number
  /** Voice calls made for this plan so far (the polish pass): the receipt's "takes voiced". */
  takes_voiced?: number
  log: PlanLogEntry[]
  items: PlanItem[]
  /** Under "draft": the job already voicing the plan. */
  job_id?: string
}

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
  /** "premade" (ElevenLabs' own), a library voice added to the account, or "mine" — one you uploaded (20i). */
  category?: string | null
  /** Volt: the vendor's own sample of a catalogue voice, when it has one. */
  preview_url?: string | null
}

/** One of your own voices (20i): uploaded under a name and cloned once. */
export interface MyVoice { voice_id: string; name: string; seconds: number; at: string; /** Volt: how it was made, and a sample to hear. */ kind?: 'recorded' | 'designed' | 'library' | 'cloned'; sample_sha?: string | null; description?: string | null; used_in?: number }
export interface Selection { start: number; end: number }

/** A score is null when it cannot be measured yet (no voice clone, no real
 *  lip-sync). `measured` names the scores taken from the media itself; any
 *  other number is simulated by the offline mock engine. */
export interface ContinuityReport {
  voice_match: number | null
  prosody: number | null
  audio_integration: number | null
  lip_sync: number | null
  /** UTMOS, when measured (20b). */
  naturalness?: number | null
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
  /** Phase 16: the picture's factor over the selection for a replaced line —
   *  1.08 is the picture 8% slower so the take fits at natural speech; null or 1 is none. */
  flex?: number | null
  /** 2026-10-20: what the line is in the mix (its level follows from it), and the user's fine-tune, dB. */
  role?: Role
  offset_db?: number | null
  /** 20b: the vendor model that spoke it, and the dials Voltage set. */
  model?: string | null
  voice_settings?: Record<string, number> | null
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
  /** The take's words with their times, relative to the take's start (Phase 14's word timestamps). */
  words?: Word[]
}

/** Recorded when the uploader confirms rights; null until they do. */
export interface ConsentRecord { granted_at: string }

export interface Project {
  /** The video's own id (folders, 2026-10-19). */
  video_id: string
  /** The folder it is in, or null. */
  project_id?: string | null
  project_name?: string | null
  filename: string
  /** Measured server-side by ffprobe — the client never asserts this. */
  duration: number
  media: MediaArtifact
  /** Bug 2: when the uploader confirmed they may edit and clone this speaker (ISO), or null. */
  consent_granted_at: string | null
  transcript: Word[]
  /** Absent from responses of servers before Phase 10. */
  statements?: Statement[]
  /** Absent from responses of servers before Phase 11. */
  speakers?: Speaker[]
  /** Absent from responses of servers before Phase 12. */
  settings?: ProjectSettings
  /** The latest plan, if the agent has made one (Phase 13). */
  plan?: Plan | null
  /** Voltage's first look at the clip, once it has had one (UX-2). */
  reading?: Reading | null
  /** 2026-10-20: the chips above Voltage's box, from this video. */
  suggestions?: Suggestion[]
  /** UX-5: a clip with no speech shows its frames where the transcript would be. */
  frames?: FrameRef[]
}

/** One speaker's role in the clip, as Voltage guesses it from what they say. */
export interface RoleGuess { label: string; role: string; why: string }

/** Voltage's first look at a clip: a specific opening line and a role per speaker. */
export interface Reading { opening: string; roles: RoleGuess[]; at?: string; /** UX-5: what Voltage saw, on a clip with no speech. */ sight?: Sight | null; /** 2026-10-20: the first chips. */ suggestions?: Suggestion[] }
/** 2026-10-20: a chip above Voltage's box, from this video: what it says, what it puts in the box, what kind, what it points at. */
export type SuggestionKind = 'fix' | 'change' | 'add' | 'voice' | 'finish'
export interface Suggestion { label: string; prompt: string; kind: SuggestionKind; grounded_in: 'time' | 'words' | 'frames' | 'brief' }
/** 2026-10-20: what Voltage sees in the video, as a piece. */
export interface Beat { at: number; kind: 'cut' | 'motion' | 'audio' | 'visual'; label: string; confidence: number; source: 'signal' | 'vision' | 'user' }
export interface Understanding {
  version: number
  read?: { format?: string; genre?: string; summary?: string; setting?: string; subjects?: string; audio_notes?: string; on_screen_text?: string[] } | null
  beats: Beat[]
  corrections: { text: string; at: string; beat_at?: number; label?: string; remove?: boolean }[]
  style?: { line: string; accepted: boolean; by: 'voltage' | 'user' } | null
  signals?: { orientation?: string; energy?: number[]; energy_step?: number } | null
}

/** What Voltage saw in a clip with no speech (UX-5). */
export interface Sight {
  opening: string
  setting: string
  mood: string
  people: string
  text_on_screen: string
  place_guess: string
  confidence: string
  beats: { at: number; note: string }[]
  /** Three to five short things worth noticing. */
  details?: string[]
  /** The place as the user confirmed or corrected it. */
  place_confirmed?: string
}

/** A still of the picture, served at /projects/{id}/frames/{index} (UX-5). */
export interface FrameRef { index: number; at: number }

/** What a project has spent. USD is an estimate from list prices. */
export interface Usage {
  spent_usd: number
  ceiling_usd: number
  /** Folders (2026-10-19): the project's ceiling and spend, when the video is in one. */
  project_ceiling_usd?: number | null
  project_spent_usd?: number | null
  /** With sign-in on: the person's spend across every project, and their cap. */
  user_spent_usd?: number | null
  user_ceiling_usd?: number | null
  voice_characters: number
  voice_characters_ceiling: number
  lines: { vendor: string; what: string; unit: string; units: number; usd: number; calls: number }[]
}

/** A row of the start screen's project list. */
export interface ProjectSummary {
  /** The video's own id (folders, 2026-10-19). */
  video_id: string
  /** The folder it is in, or null. */
  project_id?: string | null
  project_name?: string | null
  filename: string
  duration: number
  created_at: string
  edits: number
  /** UX-3: the source media (for a frame), where the project stands, its last change. */
  media?: MediaArtifact
  state?: 'new' | 'draft' | 'shipped'
  last_change?: string
  variant_of?: string | null
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
  /** The other half of a shifted line (UX-1c). */
  partner?: string | null
  /** 2026-10-20: what it is in the mix, and the fine-tune. */
  role?: Role
  offset_db?: number | null
  /** Volt: the line's speaker and the voice that said it, when known. */
  speaker?: string | null
  voice_profile_id?: string | null
}

/** A reopened project: the upload plus what has been done to it. */
export interface ProjectDetail extends Project {
  edits: ApprovedEditSummary[]
  messages: ChatMessage[]
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
export interface Insert { at: number; duration: number; artifact: MediaArtifact; /** Phase 16: seconds of frozen frame left for this insert (0 when the living hold took it all). */ held?: number }

/** Phase 16: a stretch of the output. Source [start, end] maps to render
 *  [out_start, out_end]. A "hold" has start === end (one frame held); a
 *  "living" piece is a pause stretched to make room for an added line; a
 *  "flex" piece is a replaced line's picture slowed or sped a touch so the
 *  take fits at natural speech; "copy" is untouched. Pieces tile the render. */
export interface Piece { start: number; end: number; out_start: number; out_end: number; kind: 'copy' | 'flex' | 'living' | 'hold'; factor: number | null }

/** `render` is the finished MP4, stored like any other artifact. */
export interface ExportManifest { segments: Segment[]; render: MediaArtifact; inserts?: Insert[]; pieces?: Piece[]; /** 20e: the proposals this render carries. */ proposals?: string[]; /** Bug 1: what it was built from (video, mode, edit set), the mode, whether it was reused, the caller's request id. */ edit_hash?: string; mode?: 'final' | 'proposals'; cached?: boolean; request_id?: number | null; /** 2026-10-20: what the mix did with each line, and the loudness it landed on. */ mix?: MixReport | null; /** 2026-10-20: the render's version (v1, v2...), its id, when it was made, and the takes it carries. */ version?: number; render_id?: string; created_at?: string; includes?: RenderIncludes }

/** A message in the thread. `step` is one thing Voltage did (Phase 20), with what it cost. */
/** One preview of a voice Voltage designed (20b): playable from its artifact. */
export interface VoicePreview { n: number; generated_voice_id: string; sha256: string; duration: number }
export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  /** say: words; step: one thing Voltage did; previews: voices to hear (a card). */
  kind?: 'say' | 'step' | 'previews'
  cost?: number
  seq?: number
  data?: { description?: string; previews?: VoicePreview[]; /** Volt: a step message's tool and clock. */ tool?: string; t?: number; /** Help (2026-10-19): the articles a search_help step used. */ help?: HelpRef[] }
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

/** What a plan item needs you for instead of being voiced: how to mix, or
 *  how to fit the line. Answered in words, as the next turn. */
export interface Question {
  type: 'question'
  question: string
  text: string
  mix: Mix | null
  options: QuestionOption[]
}

/** Phase 20: what a turn of Voltage leaves behind — the plan as it stands,
 *  its closing line, and the one thing it asks. */
export interface TurnResult { type: 'turn'; plan: Plan | null; reply: string; question: PlanQuestion | null; spend?: SpendSummary }

/** Spend scopes (2026-10-19), narrowest first: a turn, a video, a project, the month. */
export type SpendScopeKey = 'turn' | 'video' | 'project' | 'month'
/** One scope: what it spent, its ceiling (null: none set) and its label ("This video", "Project Diwali", "October"). */
export interface SpendScope { spent_usd: number; ceiling_usd: number | null; label: string }
/** `GET /spend`: every scope for the context, and the one with the least headroom. */
export interface SpendSummary {
  turn?: SpendScope
  video?: SpendScope
  project?: SpendScope
  month: SpendScope
  binding: SpendScopeKey | null
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

/** A turn runs server-side and is polled; it takes minutes once lip-sync is a
 *  real vendor. */
export interface Job {
  job_id: string
  kind: string
  project_id: string
  status: JobStatus
  progress: number   // 0–1
  step: string       // human-readable, shown while waiting
  attempts: number
  result: Plan | TurnResult | null
  error: string | null
}

// ── Volt (2026-10-18): the account pages and the editor's new facts ──────────

/** Your defaults for new projects, and what still asks under Just do it. */
export interface AskBefore { ship: boolean; clone: boolean; design: boolean }
export interface UserSettings { autonomy: Autonomy; turn_usd: number; effort: Effort; ask_before: AskBefore }

/** Spend across your projects for a period (the Usage page). */
export interface UsageReport {
  period: 'week' | 'month' | 'all'
  spent_usd: number
  /** Your ceiling across projects; the project ceiling is `project_cap_usd`. */
  ceiling_usd: number
  project_cap_usd: number
  turns: number
  takes: number
  voices_made: number
  avg_turn_usd: number
  by_vendor: { vendor: string; label: string; usd: number }[]
  by_video: { video_id: string; filename: string; turns: number; voice_characters: number; spent_usd: number; cap_usd: number }[]
  /** Folders (2026-10-19). */
  by_project: { project_id: string; name: string; videos: number; turns: number; spent_usd: number; ceiling_usd: number | null }[]
  /** Spend scopes: projects with their videos nested (spent while in that project), "No project" last. */
  groups?: UsageGroup[]
  /** The chosen scope's totals. */
  totals?: UsageTotals
}

export interface UsageGroup {
  /** null for "No project". */
  project_id: string | null
  name: string
  ceiling_usd: number | null
  /** Costs that belong to no single video; null for "No project". */
  project_level_usd: number | null
  spent_usd: number
  /** `here`: the video is in this project now (false: it spent here, then moved). */
  videos: { video_id: string; filename: string; spent_usd: number; here: boolean }[]
}
export interface UsageTotals { scope: string; label: string; spent_usd: number; ceiling_usd: number | null; by_vendor: { vendor: string; label: string; usd: number }[] }

/** A voice made inside one of your projects (designed, added from the library, or a speaker's clone); deleted with the project unless kept. */
export interface MadeVoice { voice_id: string; name: string; kind: 'designed' | 'library' | 'cloned'; video_id: string; filename: string; description?: string | null; seconds?: number | null; kept?: boolean }
/** A speaker in one of your projects with enough speech to clone. */
export interface CloneableSpeaker { video_id: string; filename: string; label: string; name: string; seconds: number }
/** A preview of a voice designed from words, outside any project. */
export interface DesignedPreview { generated_voice_id: string; sha256: string; duration: number; text: string }

/** What went into the file, for the Export page. */
export interface Receipt {
  turns: number
  takes: number
  spent_usd: number
  changes: { edit_id: string; start: number; text: string; kind: 'changed' | 'added' | 'removed'; note: string }[]
  drafts: number
  render: { sha256: string; duration: number; filename: string } | null
}

/** Projects as folders (2026-10-19): a folder of videos with what they share. */
export interface ProjectFolder {
  project_id: string
  name: string
  brief: string
  settings?: ProjectSettings
  ceiling_usd: number | null
  spent_usd: number
  created_at: string
  last_at?: string | null
  video_count?: number
  voices?: number
  files?: number
}
export interface ProjectFile { name: string; sha256: string; size: number; kind: string; at: string }
export interface BriefSuggestion { id: string; text: string; why?: string | null; video_id?: string | null; filename?: string | null; at: string }
export interface ProjectVoice extends MyVoice { project_id?: string; project_name?: string; used_in?: number; /** Bug 2: the moment consent was given (ISO) or null; approximate when backfilled; not needed for a designed voice. */ consent_granted_at?: string | null; consent_approximate?: boolean; consent_needed?: boolean }
export interface ProjectDetailFolder {
  project: ProjectFolder
  videos: ProjectSummary[]
  voices: ProjectVoice[]
  files: ProjectFile[]
  suggestions: BriefSuggestion[]
}

/** Help articles (Tutorial map and Help, 2026-10-19): one Markdown file each, read by the Help page and by Voltage's search_help. */
export interface HelpArticle { slug: string; section: string; title: string; summary: string; body: string; order?: number; tour?: string | null }
/** What a person has met so far: the tour, the tips seen, the checklist. */
export interface Onboarding {
  tour: { step: number; finished: boolean; skipped: boolean }
  tips: string[]
  checklist: string[]
  checklist_hidden: boolean
}

/** An article a search_help step used, as the pane links it. */
export interface HelpRef { slug: string; title: string; section: string; tour?: string | null }

// ── One processing model (2026-10-20) ─────────────────────────────────────────
// Every surface (the status strip, Activity, the row chips, the player's badge,
// the chat's step list, toasts, the tab title) reads from these records.

export type ActivityKind = 'voice_line' | 'design_voice' | 'clone' | 'mix' | 'render_preview' | 'export'
export type ActivityStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
/** The takes a render carries: kept edits, proposals (items), and their candidates. */
export interface RenderIncludes { candidate_ids: string[]; edit_ids: string[]; item_ids: string[] }
export interface ActivityJob {
  job_id: string
  video_id: string
  turn_id: string | null
  kind: ActivityKind
  status: ActivityStatus
  step_label: string
  progress: number
  /** Plan item ids ("i3") and edit ids ("e2") the job is about. */
  line_ids: string[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  /** Whole seconds, at least 1, while queued or running; null when finished or unknown. */
  eta_s: number | null
  error_code: string | null
  error_text: string | null
  cost_usd: number | null
  retryable?: boolean
  detail?: {
    text?: string; voice_name?: string; chars?: number
    version?: number; mode?: 'final' | 'proposals'; render_id?: string; includes?: RenderIncludes
    manual?: boolean
  }
}
export interface TurnView {
  turn_id: string
  status: 'running' | 'stopping' | 'done' | 'failed'
  step: string
  started_at: string
  finished_at: string | null
  spent_usd?: number
  lines_voiced?: number
  render?: { version: number; mode: 'final' | 'proposals'; render_id?: string } | null
}
export interface RenderRecord {
  render_id: string
  version: number
  edit_set_hash: string
  created_at: string
  mode: 'final' | 'proposals'
  render: MediaArtifact
  manifest?: ExportManifest
  includes?: RenderIncludes
}
export interface RenderInProgress {
  render_id: string; version: number; edit_set_hash: string; started_at: string; eta_s: number | null; job_id: string
  includes?: RenderIncludes
}
export interface RenderState {
  mode: 'final' | 'proposals'
  current_hash: string
  latest: RenderRecord | null
  in_progress: RenderInProgress | null
  stale: boolean
}
