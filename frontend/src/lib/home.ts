/** Home's ordering, filtering and search links (D4), kept apart from the components. */
import type { ProjectSummary, SearchHit } from '../types'
import { hrefFor } from './route'

// D4: how Recent videos can be ordered and narrowed.
export type Sort = 'edited' | 'created' | 'name' | 'stage'
export const SORTS: { key: Sort; label: string }[] = [{ key: 'edited', label: 'Last edited' }, { key: 'created', label: 'Created' }, { key: 'name', label: 'Name' }, { key: 'stage', label: 'Stage' }]
export const STAGES: { key: string; label: string }[] = [
  { key: 'draft', label: 'Draft' }, { key: 'in_review', label: 'In review' }, { key: 'changes_asked', label: 'Changes asked' }, { key: 'approved', label: 'Approved' }, { key: 'exported', label: 'Exported' },
]
const stageRank = (s?: string) => { const i = STAGES.findIndex((x) => x.key === (s ?? 'draft')); return i < 0 ? 0 : i }
/** Brief changed, out of sync with its master, or open review comments. */
export const needsAttention = (p: ProjectSummary) => !!p.brief_changed || !!p.out_of_sync || (p.open_comments ?? 0) > 0
export function sortVideos(list: ProjectSummary[], by: Sort): ProjectSummary[] {
  const edited = (p: ProjectSummary) => p.last_edited_at ?? p.created_at
  const out = [...list]
  if (by === 'edited') out.sort((a, b) => edited(b).localeCompare(edited(a)))
  else if (by === 'created') out.sort((a, b) => b.created_at.localeCompare(a.created_at))
  else if (by === 'name') out.sort((a, b) => a.filename.localeCompare(b.filename, undefined, { sensitivity: 'base' }))
  else out.sort((a, b) => stageRank(a.stage) - stageRank(b.stage) || a.filename.localeCompare(b.filename))
  return out
}


/** Where a hit opens: a spoken word at its time in the editor, a video, or its project. */
export function hitHref(hit: SearchHit, projectId: string | null): string {
  if (hit.kind === 'transcript' && hit.video_id) return hrefFor({ page: 'editor', projectId: hit.video_id, t: hit.at ?? 0 })
  if (hit.kind === 'video' && hit.video_id) return hrefFor({ page: 'editor', projectId: hit.video_id })
  return projectId ? hrefFor({ page: 'folder', projectId }) : hrefFor({ page: 'projects' })
}

