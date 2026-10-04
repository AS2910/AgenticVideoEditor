import { useState } from 'react'
import type { ProjectSummary } from '../types'
import { artifactUrl } from '../api'
import styles from './ProjectList.module.css'

interface ProjectListProps {
  projects: ProjectSummary[]
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const STATE: Record<string, string> = { new: 'New', draft: 'Draft', shipped: 'Shipped' }

/** Past projects, to reopen or delete: a frame, where each stands, and its
 *  last change (UX-3). Deleting asks once more, inline. */
export function ProjectList({ projects, onOpen, onDelete }: ProjectListProps) {
  const [confirming, setConfirming] = useState<string | null>(null)
  if (projects.length === 0) return null
  const nameOf = (id: string) => projects.find((p) => p.project_id === id)?.filename
  return (
    <section className={styles.list} aria-labelledby="recent-title">
      <h2 id="recent-title" className={styles.heading}>Recent</h2>
      <ul className={styles.rows}>
      {projects.map((p) => (
        <li key={p.project_id} className={styles.row}>
          <button className={styles.open} onClick={() => onOpen(p.project_id)}>
            {p.media ? (
              <video className={styles.frame} muted playsInline preload="metadata" tabIndex={-1} aria-hidden="true"
                src={`${artifactUrl(p.project_id, p.media.sha256)}#t=0.5`} />
            ) : <span className={styles.frame} />}
            <span className={styles.text}>
              <span className={styles.line}>
                <span className={styles.name}>{p.filename}</span>
                {p.state && <span className={styles.state} data-state={p.state}>{STATE[p.state] ?? p.state}</span>}
                {p.variant_of && <span className={styles.meta}>variant{nameOf(p.variant_of) ? ` of ${nameOf(p.variant_of)}` : ''}</span>}
              </span>
              <span className={styles.meta}>
                {when(p.created_at)}, {p.duration.toFixed(1)} s{p.last_change ? ` · ${p.last_change}` : `, ${p.edits} ${p.edits === 1 ? 'edit' : 'edits'}`}
              </span>
            </span>
          </button>
          {confirming === p.project_id ? (
            <>
              <button className={styles.confirm} onClick={() => onDelete(p.project_id)}>
                Delete for good
              </button>
              <button className={styles.cancel} onClick={() => setConfirming(null)}>Keep</button>
            </>
          ) : (
            <button
              className={styles.delete}
              aria-label={`Delete ${p.filename}`}
              onClick={() => setConfirming(p.project_id)}
            >
              Delete
            </button>
          )}
        </li>
      ))}
      </ul>
    </section>
  )
}
