import type { ProjectEvent, Stage } from '../types'

/** C1: the project feed's words. Each activity-log event (F7) reads as one
 *  plain sentence ("Priya approved bhaji-cam-ad v5", "Voltage voiced 4 lines
 *  in reels-cut", "You moved promo to Approved"); a run of lines added or
 *  taken out of one video by one actor reads as one item. */

export const STAGE_LABEL: Record<Stage, string> = {
  draft: 'Draft', in_review: 'In review', changes_asked: 'Changes asked', approved: 'Approved', exported: 'Exported',
}
export const STAGES: Stage[] = ['draft', 'in_review', 'changes_asked', 'approved', 'exported']

/** A file name as the feed says it: without its extension. */
export const videoWord = (filename: string | null | undefined) => (filename ? filename.replace(/\.[a-z0-9]{2,4}$/i, '') : 'a video')

export interface FeedItem { key: string; events: ProjectEvent[]; text: string; at: string; actor: ProjectEvent['actor_kind'] }

const lines = (n: number) => `${n} ${n === 1 ? 'line' : 'lines'}`
const GROUPED = new Set(['edit.shipped', 'edit.undone'])
// C2: a reviewer's answer is said by its stage move; only a note of theirs is a line of its own.
const QUIET = (e: ProjectEvent) => (e.verb === 'review.approved' || e.verb === 'review.changes_asked') && !e.payload.note

function who(e: ProjectEvent): string {
  if (e.you) return 'You'
  if (e.actor_kind === 'voltage') return 'Voltage'
  return e.actor_name || (e.actor_kind === 'reviewer' ? 'A reviewer' : 'Someone')
}

function stageSentence(e: ProjectEvent, by: string, video: string): string {
  const to = String(e.payload.to ?? '') as Stage
  const why = String(e.payload.why ?? '')
  const label = STAGE_LABEL[to] ?? to
  if (e.actor_kind === 'reviewer' && to === 'approved') {
    const v = typeof e.payload.version === 'number' ? e.payload.version : (why.match(/\bv(\d+)\b/)?.[1] ?? null)
    return `${by} approved ${video}${v ? ` v${v}` : ''}`
  }
  if (e.actor_kind === 'reviewer' && to === 'changes_asked') return `${by} asked for changes to ${video}`
  if (to === 'draft' && /new edit was added after approval/i.test(why)) return `${video} went back to Draft: a new edit was added after it was approved`
  if (to === 'in_review' && /^review link sent/i.test(why)) {
    const name = why.match(/^Review link sent to (.+?)\.?$/i)?.[1]
    return `${by} sent ${video} for review${name ? ` to ${name}` : ''}`
  }
  if (to === 'exported' && /^exported/i.test(why)) return `${by} exported ${video}`
  return `${by} moved ${video} to ${label}`
}

const clockOf = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

/** One event (or a run of the same line events) as a sentence. */
export function sentence(events: ProjectEvent[], nameOf: (videoId: string | null) => string | null): string {
  const e = events[0]
  const by = who(e)
  const video = videoWord(nameOf(e.video_id))
  const p = e.payload
  const n = events.length
  switch (e.verb) {
    case 'stage.moved': return stageSentence(e, by, video)
    case 'edit.shipped': return e.actor_kind === 'voltage' ? `Voltage voiced ${lines(n)} in ${video}` : `${by} added ${lines(n)} to ${video}`
    case 'edit.undone': return `${by} took ${lines(n)} out of ${video}`
    case 'brief.saved': return `${by} saved the brief${p.version ? ` as v${p.version}` : ''}`
    case 'rule.added': return `${by} added a word rule`
    case 'rule.changed': return `${by} changed a word rule`
    case 'rule.removed': return `${by} removed a word rule`
    case 'video.moved_in': return `${by} moved ${video} into this project`
    case 'video.moved_out': return `${by} moved ${video} out of this project`
    case 'video.deleted': return `${by} deleted ${video}`
    case 'video.restored': return `${by} restored ${video}`
    case 'brief.update_started': return `${by} started bringing ${Array.isArray(p.videos) ? `${p.videos.length} ${p.videos.length === 1 ? 'video' : 'videos'}` : 'videos'} up to date with the brief`
    case 'brief.video_current': return `Voltage marked ${video} current with the brief, nothing to change`
    case 'brief.update_finished': return 'Bringing videos up to date with the brief finished'
    case 'check.started': return `${by} checked the project`
    case 'check.finished': return `The project check found ${p.issues ?? 0} ${p.issues === 1 ? 'issue' : 'issues'}`
    case 'check.issue_ignored': return `${by} ignored an issue from the check`
    case 'check.fix_started': return `${by} asked Voltage to fix ${video}`
    case 'check.fix_all_started': return `${by} asked Voltage to fix an issue in every video`
    case 'check.fix_all_finished': return 'Fixing an issue in every video finished'
    case 'batch.planned': return `${by} asked Voltage about ${Array.isArray(p.videos) ? `${p.videos.length} ${p.videos.length === 1 ? 'video' : 'videos'}` : 'the videos'}`
    case 'batch.started': return `${by} started a batch`
    case 'batch.finished': return 'A batch finished'
    case 'batch.cancelled': return `${by} stopped a batch`
    case 'batch.answered': return `${by} answered Voltage in ${video}`
    case 'batch.added_all': return `${by} added all that passed in ${p.videos && typeof p.videos === 'object' ? Object.keys(p.videos).length : 0} videos`
    case 'batch.add_undone': return `${by} undid the batch's lines in ${video}`
    case 'language.versions_made': return Array.isArray(p.languages) ? `${by} made ${p.languages.length} language ${p.languages.length === 1 ? 'version' : 'versions'} of ${video}` : `${by} made language versions of ${video}`
    case 'language.sync_started': return `${by} started syncing ${video} with its master`
    case 'language.synced': return `${video} is in step with its master`
    case 'export.started': return typeof p.files === 'number' ? `${by} started exporting ${p.files} ${p.files === 1 ? 'file' : 'files'}` : `${by} started an export`
    case 'export.finished': return `An export finished: ${p.ready ?? 0} ready${p.failed ? `, ${p.failed} failed` : ''}`
    case 'share.created': return `${by} made a ${p.role === 'reviewer' ? 'review' : 'share'} link${p.scope === 'video' ? ` to ${video}` : ''}`
    case 'share.revoked': return `${by} turned off a link`
    case 'review.commented': return `${by} commented on ${video}${typeof p.at_s === 'number' ? ` at ${clockOf(p.at_s)}` : ''}`
    case 'review.approved': return `${by} approved ${video} with a note: "${String(p.note ?? '')}"`
    case 'review.changes_asked': return `${by} asked for changes to ${video}: "${String(p.note ?? '')}"`
    case 'review.replied': return `${by} replied to a comment on ${video}`
    case 'review.resolved': return `${by} resolved a comment on ${video}`
    case 'review.reopened': return `${by} opened a comment on ${video} again`
    default: return `${by} ${e.verb.replace(/[._]/g, ' ')}${e.video_id ? ` in ${video}` : ''}`
  }
}

/** Events (newest first) as feed items, a run of line events folded into one. */
export function feedItems(events: ProjectEvent[], nameOf: (videoId: string | null) => string | null): FeedItem[] {
  const out: ProjectEvent[][] = []
  for (const e of events) {
    if (QUIET(e)) continue
    const last = out[out.length - 1]
    const head = last?.[0]
    if (head && GROUPED.has(e.verb) && head.verb === e.verb && head.video_id === e.video_id
      && head.actor_kind === e.actor_kind && head.actor_name === e.actor_name) last.push(e)
    else out.push([e])
  }
  return out.map((run) => ({ key: String(run[0].id), events: run, text: sentence(run, nameOf), at: run[0].at, actor: run[0].actor_kind }))
}

/** The warning's words for one or more Approved videos (the server says the same in its 409). */
export function approvedWords(filenames: string[]): string {
  if (filenames.length <= 1) return 'This video is Approved. Adding this moves it back to Draft.'
  return `${filenames.length} videos are Approved (${filenames.join(', ')}). Adding these moves them back to Draft.`
}
