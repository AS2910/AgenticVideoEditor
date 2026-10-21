import { useEffect, useRef, useState } from 'react'
import { track } from '../lib/analytics'
import type { DragEvent, KeyboardEvent } from 'react'
import type { ProjectSummary, Stage } from '../types'
import { moveStage } from '../api'
import { hrefFor } from '../lib/route'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'
import { Frame } from './bits'
import { STAGES, STAGE_LABEL } from './feedWords'

/** C1 (projects.review): the project's videos by stage. Drag a card to a
 *  column, or use its Move to menu (the keyboard and single-pointer way);
 *  each move is one POST /videos/{id}/stage, so one event in the feed. */

const DRAG_TYPE = 'application/x-voltage-video'
const stageOf = (v: ProjectSummary): Stage => (STAGES.includes(v.stage as Stage) ? v.stage as Stage : 'draft')

interface BoardProps {
  videos: ProjectSummary[]
  /** Chips: "Brief changed" (projects.consistency) and "Out of sync" (projects.batch). */
  briefChips?: boolean
  syncChips?: boolean
  /** A move was made (or undone after a refusal): the page updates its list and the feed. */
  onMoved: (videoId: string, stage: Stage) => void
}

export function ProjectBoard({ videos, briefChips, syncChips, onMoved }: BoardProps) {
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<Stage | null>(null)
  const [said, setSaid] = useState('')
  const [error, setError] = useState<string | null>(null)

  const move = async (v: ProjectSummary, to: Stage) => {
    const from = stageOf(v)
    if (from === to) return
    setError(null)
    onMoved(v.video_id, to)
    try {
      await moveStage(v.video_id, to)
      setSaid(`Moved ${v.filename} to ${STAGE_LABEL[to]}.`)
      track('board.card_moved', { from, to })
    } catch (e) {
      onMoved(v.video_id, from)
      setError(e instanceof Error ? `Could not move ${v.filename}. ${e.message}` : `Could not move ${v.filename}.`)
    }
  }

  const dropOn = (to: Stage) => (e: DragEvent) => {
    const id = e.dataTransfer.getData(DRAG_TYPE) || dragging
    setOver(null)
    setDragging(null)
    if (!id) return
    e.preventDefault()
    const v = videos.find((x) => x.video_id === id)
    if (v) void move(v, to)
  }

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="board">
      {error && <div className="rounded-lg border-[1.5px] border-warn bg-card px-3.5 py-2.5 text-sm" role="alert">{error}</div>}
      <span className="sr-only" role="status" aria-live="polite">{said}</span>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-[repeat(5,minmax(168px,1fr))] sm:overflow-x-auto sm:pb-1">
        {STAGES.map((stage) => {
          const here = videos.filter((v) => stageOf(v) === stage)
          return (
            <section
              key={stage} aria-label={`${STAGE_LABEL[stage]}, ${here.length} ${here.length === 1 ? 'video' : 'videos'}`} data-testid={`column-${stage}`} data-over={over === stage || undefined}
              className={cn('flex min-h-[160px] min-w-0 flex-col gap-2 rounded-xl border-[1.5px] border-dashed border-line2 bg-sunk p-2.5 transition-colors', over === stage && 'border-foreground bg-card')}
              onDragOver={(e) => { if (!dragging && !e.dataTransfer.types.includes(DRAG_TYPE)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (over !== stage) setOver(stage) }}
              onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((o) => (o === stage ? null : o)) }}
              onDrop={dropOn(stage)}
            >
              <div className="flex items-center gap-2 px-0.5">
                <span className={cn('stamp', stage === 'approved' ? '' : stage === 'changes_asked' ? 'need' : stage === 'draft' ? 'quiet' : 'in')}>{STAGE_LABEL[stage]}</span>
                <span className="tnum text-xs text-faint">{here.length}</span>
              </div>
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {here.map((v) => (
                  <BoardCard key={v.video_id} v={v} briefChips={briefChips} syncChips={syncChips} lifted={dragging === v.video_id}
                    onDragStart={(e) => { e.dataTransfer.setData(DRAG_TYPE, v.video_id); e.dataTransfer.effectAllowed = 'move'; setDragging(v.video_id) }}
                    onDragEnd={() => { setDragging(null); setOver(null) }}
                    onMove={(to) => void move(v, to)} />
                ))}
              </ul>
              {here.length === 0 && <span className="px-0.5 text-[13px] text-faint">{dragging ? 'Drop here' : 'Nothing here'}</span>}
            </section>
          )
        })}
      </div>
    </div>
  )
}

function BoardCard({ v, briefChips, syncChips, lifted, onDragStart, onDragEnd, onMove }: {
  v: ProjectSummary; briefChips?: boolean; syncChips?: boolean; lifted: boolean
  onDragStart: (e: DragEvent) => void; onDragEnd: () => void; onMove: (to: Stage) => void
}) {
  const [menu, setMenu] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const now = stageOf(v)
  const comments = v.open_comments ?? 0
  const name = `${v.filename}${v.language_label ? ` · ${v.language_label}` : ''}`

  useEffect(() => {
    if (!menu) return
    list.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(`[data-board-menu="${v.video_id}"]`)) setMenu(false) }
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu, v.video_id])

  const onMenuKey = (e: KeyboardEvent) => {
    const items = [...(list.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])]
    const at = items.indexOf(document.activeElement as HTMLButtonElement)
    if (e.key === 'Escape') { e.preventDefault(); setMenu(false); button.current?.focus() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1) % items.length]?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus() }
  }

  return (
    <li
      draggable onDragStart={onDragStart} onDragEnd={onDragEnd} data-testid="board-card" data-video={v.video_id}
      className={cn('flex cursor-grab flex-col gap-2 rounded-[10px] border-[1.5px] border-foreground bg-card p-2 active:cursor-grabbing', lifted && 'opacity-50')}
    >
      <a href={hrefFor({ page: 'editor', projectId: v.video_id })} draggable={false} className="flex flex-col gap-1.5 text-foreground no-underline">
        <span className="relative block aspect-[16/10] overflow-hidden rounded-md border border-ink bg-pic">
          <Frame id={v.video_id} />
          <span className="tnum absolute right-1.5 bottom-1.5 rounded bg-ink/60 px-1.5 text-xs text-ptext">{clock(v.duration)}</span>
        </span>
        <span className="truncate text-sm font-semibold" title={name}>{name}</span>
      </a>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="tag text-faint" data-testid="open-comments">{comments} open {comments === 1 ? 'comment' : 'comments'}</span>
        {briefChips && v.brief_changed && <span className="stamp need" data-testid="brief-changed">Brief changed</span>}
        {syncChips && v.out_of_sync && <span className="stamp need" data-testid="board-out-of-sync">Out of sync</span>}
      </div>
      <div className="relative" data-board-menu={v.video_id}>
        <button ref={button} type="button" className="act h-8 pointer-coarse:h-11" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)} aria-label={`Move ${name} to another stage`}>Move to…</button>
        {menu && (
          <div ref={list} role="menu" aria-label={`Move ${name} to`} onKeyDown={onMenuKey} className="rise absolute left-0 z-10 mt-1 flex w-48 flex-col rounded-xl border-[1.5px] border-ink bg-card p-1.5 shadow-volt">
            {STAGES.filter((s) => s !== now).map((s) => (
              <button key={s} type="button" role="menuitem" className="act justify-start" onClick={() => { setMenu(false); onMove(s); button.current?.focus() }}>{STAGE_LABEL[s]}</button>
            ))}
          </div>
        )}
      </div>
    </li>
  )
}
