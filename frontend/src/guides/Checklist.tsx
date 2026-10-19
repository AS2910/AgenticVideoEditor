import { useId, useState } from 'react'
import { cn } from '@/lib/utils'
import { FillBar } from '../pages/bits'
import { useOnboarding } from './onboarding'

export interface ChecklistItem { id: 'goal' | 'add' | 'export' | 'save-voice' | 'autonomy'; label: string; tour: string }

/** The five things to do once; each is ticked by the real action, never by hand. */
export const CHECKLIST: ChecklistItem[] = [
  { id: 'goal', label: 'Send Voltage a goal', tour: 'goal' },
  { id: 'add', label: 'Add a proposal', tour: 'add' },
  { id: 'export', label: 'Export a video', tour: 'export' },
  { id: 'save-voice', label: 'Save a voice', tour: 'save-voice' },
  { id: 'autonomy', label: 'Choose how much Voltage may do', tour: 'autonomy' },
]

/** The "Get started 2/5" pill at the bottom left, opening the checklist card.
 *  Gone once every item is done, or once it is hidden. */
export function Checklist({ onShowMe, className }: { onShowMe: (tourId: string) => void; className?: string }) {
  const { onboarding, loaded, hideChecklist } = useOnboarding()
  const [open, setOpen] = useState(false)
  const panel = useId()
  const done = CHECKLIST.filter((i) => onboarding.checklist.includes(i.id)).length
  if (!loaded || onboarding.checklist_hidden || done >= CHECKLIST.length) return null

  return (
    <div className={cn('fixed bottom-5 left-5 z-30 flex w-[300px] max-w-[calc(100vw-40px)] flex-col items-start', className)}>
      {open && (
        <section id={panel} aria-label="Get started" className="rise mb-2.5 w-full rounded-xl border-[1.5px] border-ink bg-card px-4 pt-3.5 pb-1.5 text-foreground shadow-ink-lg">
          <div className="flex items-baseline gap-2">
            <h2 className="disp m-0 text-lg font-bold">Get started</h2>
            <span className="tnum font-semibold">{done}/{CHECKLIST.length}</span>
            <span className="flex-1" />
            <button type="button" className="act h-[26px]" onClick={() => { hideChecklist(); setOpen(false) }}>Hide</button>
          </div>
          <FillBar share={done / CHECKLIST.length} height={6} label="Get started progress" className="my-2" />
          <ul className="m-0 list-none p-0">
            {CHECKLIST.map((it) => {
              const isDone = onboarding.checklist.includes(it.id)
              return (
                <li key={it.id} className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-line py-2">
                  <span aria-hidden="true" className={cn('grid size-5 place-items-center rounded-[5px] border-[1.5px] text-xs font-bold', isDone ? 'border-ink bg-volt text-ink' : 'border-foreground')}>{isDone ? '✓' : ''}</span>
                  <span className={cn('text-sm', isDone && 'text-faint line-through')}>
                    {it.label}<span className="sr-only">{isDone ? ', done' : ', to do'}</span>
                  </span>
                  {!isDone && <button type="button" className="act tag h-[26px] px-1.5 text-foreground" onClick={() => onShowMe(it.tour)}>Show me →<span className="sr-only">: {it.label}</span></button>}
                </li>
              )
            })}
          </ul>
        </section>
      )}
      <button
        type="button" aria-expanded={open} aria-controls={open ? panel : undefined} aria-label={`Get started, ${done} of ${CHECKLIST.length} done`}
        className="inline-flex h-10 items-center gap-2.5 rounded-full bg-ink px-3.5 text-volt hover:opacity-90 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="tag">Get started</span><span className="tnum font-semibold">{done}/{CHECKLIST.length}</span>
      </button>
    </div>
  )
}
