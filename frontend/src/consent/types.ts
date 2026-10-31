/** Voice consent V1 step 6: the shapes the voice guard sends (contract in
 *  docs/superpowers/plans/2026-10-31-voice-consent-v1.md, step 3). */

/** A 409 attestation_required: what the modal posts to and whose voice it is. */
export interface AttestationFacts {
  code?: 'attestation_required'
  message?: string
  /** What to post to: a voice id, or the speaker's label before their clone exists. */
  voice: string
  voice_id?: string | null
  video_id: string
  source_video_id?: string | null
  speaker_label?: string | null
  speaker_name?: string | null
  statement_version: string
}

/** One cloned voice an export uses. */
export interface ExportVoice { voice_id: string; video_id: string; speaker_label: string | null; speaker_name: string | null }

/** A 409 export_confirm_required: the reminder posts `{label_on}` to /exports/{export_ref}/confirm. */
export interface ExportFacts {
  code?: 'export_confirm_required'
  message?: string
  export_ref: string
  voices: ExportVoice[]
  videos: string[]
  label_default?: boolean
  statement_version?: string
}

export type ConsentAsk =
  | { kind: 'attestation'; facts: AttestationFacts }
  | { kind: 'export'; facts: ExportFacts }

/** A line the guard refused, as a step message carries it (`data.refusal`). */
export interface LineRefusalFacts { code: 'line_blocked' | 'line_in_review' | 'voice_unavailable'; message: string; item_id?: string; start?: number; end?: number }

/** A voice's scope, from GET /voices/scopes (the chips' "This video only"). */
export interface VoiceScope {
  voice_id: string
  scope: 'video' | 'library'
  status: 'active' | 'suspended' | 'withdrawn'
  kind: string
  source_video_id: string | null
  speaker_label: string | null
  video_only: boolean
  verified: boolean
}
