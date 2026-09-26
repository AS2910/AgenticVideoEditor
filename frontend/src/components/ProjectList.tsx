import { useState } from 'react'
import type { ProjectSummary } from '../types'
import styles from './ProjectList.module.css'

interface ProjectListProps {
  projects: ProjectSummary[]
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** Past projects, to reopen or delete. Deleting asks once more, inline. */
export function ProjectList({ projects, onOpen, onDelete }: ProjectListProps) {
  const [confirming, setConfirming] = useState<string | null>(null)
  if (projects.length === 0) return null
  return (
    <div className={styles.list}>
      <div className={styles.heading}>Your projects</div>
      {projects.map((p) => (
        <div key={p.project_id} className={styles.row}>
          <button className={styles.open} onClick={() => onOpen(p.project_id)}>
            <span className={styles.name}>{p.filename}</span>
            <span className={styles.meta}>
              {p.duration.toFixed(1)}s · {p.edits} {p.edits === 1 ? 'edit' : 'edits'} · {when(p.created_at)}
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
        </div>
      ))}
    </div>
  )
}
