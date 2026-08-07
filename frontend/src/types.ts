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

export interface Candidate {
  plan: EditPlan
  audio_ref: string
  frames_ref: string
  continuity: ContinuityReport
}

export interface Project { project_id: string; transcript: Word[] }
export interface ApprovedResult { edit_id: string; continuity: ContinuityReport }
export interface Segment { start: number; end: number; kind: 'original' | 'edited'; ref: string }
export interface ExportManifest { segments: Segment[] }

export interface EditRequest {
  prompt: string
  start: number
  end: number
  voice_profile_id: string
}
