import { useEffect, useRef, useState } from 'react'
import type { ProjectSummary } from '../types'
import { artifactUrl } from '../api'
import styles from './ProjectList.module.css'

interface ProjectListProps {
  projects: ProjectSummary[]
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  /** How long "Deleted · Undo" waits before the delete goes through. */
  undoMs?: number
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const STATE: Record<string, string> = { new: 'New', draft: 'Draft', shipped: 'Shipped' }

/** Past projects, to reopen or delete: a frame, where each stands, and its
 *  last change (UX-3). Deleting asks once more in a strip that is not under
 *  the finger that tapped Delete, and then waits a few seconds with Undo
 *  before anything is gone (UX-6). */
export function ProjectList({ projects, onOpen, onDelete, undoMs = 5000 }: ProjectListProps) {
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirming) keep.current?.focus() }, [confirming])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  if (projects.length === 0) {
    return <p className={styles.empty}>Your projects will show here after your first upload.</p>
  }
  const nameOf = (id: string) => projects.find((p) => p.project_id === id)?.filename
  const begin = (id: string) => {
    setConfirming(null)
    setDeleting(id)
    timer.current = setTimeout(() => { timer.current = null; setDeleting(null); onDelete(id) }, undoMs)
  }
  const undo = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setDeleting(null)
  }
  return (
    <section className={styles.list} aria-labelledby="recent-title">
      <h2 id="recent-title" className={styles.heading}>Recent</h2>
      <ul className={styles.rows}>
      {projects.map((p) => (
        <li key={p.project_id} className={styles.row}>
          {deleting === p.project_id ? (
            <div className={styles.strip} role="status">
              <span>Deleted <strong>{p.filename}</strong>.</span>
              <button className={styles.undo} onClick={undo}>Undo</button>
            </div>
          ) : confirming === p.project_id ? (
            <div className={styles.strip} role="group" aria-label={`Delete ${p.filename}?`}>
              <span>Delete <strong>{p.filename}</strong> for good? Its media and every take go with it.</span>
              <button ref={keep} className={styles.cancel} onClick={() => setConfirming(null)}>Keep</button>
              <button className={styles.confirm} onClick={() => begin(p.project_id)}>Delete for good</button>
            </div>
          ) : (
            <>
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
              <button
                className={styles.delete}
                aria-label={`Delete ${p.filename}`}
                onClick={() => setConfirming(p.project_id)}
              >
                Delete
              </button>
            </>
          )}
        </li>
      ))}
      </ul>
    </section>
  )
}
