import { useRef } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'

interface KeyboardSheetProps { open: boolean; onClose: () => void }

type Row = { keys: string[]; what: string; hot?: boolean }
const MOVE: Row[] = [
  { keys: ['↑', '↓'], what: 'Move between lines' },
  { keys: ['Space'], what: 'Hear the line or proposal in place' },
  { keys: ['Enter'], what: "Open the line's editor" },
  { keys: ['Esc'], what: 'Close the editor or this sheet' },
  { keys: ['/'], what: 'Ask Voltage: cursor to its box' },
  { keys: ['?'], what: 'Open this sheet', hot: true },
]
const CHANGE: Row[] = [
  { keys: ['K'], what: 'Add the proposal to the video', hot: true },
  { keys: ['U'], what: 'Undo, or take an added line out' },
  { keys: ['A'], what: 'Add a line after this one' },
  { keys: ['Delete'], what: 'Discard, or propose removing a line' },
  { keys: ['S'], what: 'Shift a line to a new time' },
]

/** A keycap: mono, ink-bordered, a thicker bottom edge; volt for the two keys that matter most. */
export const Keycap = ({ k, hot }: { k: string; hot?: boolean }) => (
  <kbd className={cn('tnum inline-grid h-[34px] min-w-[34px] place-items-center rounded-[7px] border-[1.5px] border-b-[3px] border-ink px-2 text-sm font-semibold not-italic', hot ? 'bg-volt text-ink' : 'bg-card text-foreground')}>{k}</kbd>
)

function Column({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <div>
      <div className="tag pb-1.5 text-faint">{title}</div>
      <dl className="m-0">
        {rows.map((r) => (
          <div key={r.what} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3.5 border-t border-line py-2">
            <dt className="flex gap-1.5">{r.keys.map((k) => <Keycap key={k} k={k} hot={r.hot} />)}</dt>
            <dd className="m-0">{r.what}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Every shortcut of the transcript, on `?` (the host binds it); Esc closes.
 *  A real dialog: focus lands on the title, Tab stays inside, focus returns. */
export function KeyboardSheet({ open, onClose }: KeyboardSheetProps) {
  const title = useRef<HTMLHeadingElement>(null)
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="max-h-[calc(100dvh-2rem)] overflow-auto rounded-xl border-[1.5px] border-ink bg-card p-5 text-foreground shadow-volt-lg sm:max-w-[860px] sm:px-8 sm:py-7"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <Keycap k="?" hot />
          <DialogTitle ref={title} tabIndex={-1} className="disp text-[30px] font-bold outline-none">Keyboard</DialogTitle>
          <span className="tag text-faint">work through a transcript without the mouse</span>
          <span className="flex-1" />
          <button type="button" className="btn" onClick={onClose}>Esc · Close</button>
        </div>
        <div className="grid grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2">
          <Column title="Move and listen" rows={MOVE} />
          <Column title="Change" rows={CHANGE} />
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t-[1.5px] border-foreground pt-3.5 text-[13px] text-muted-foreground">
          <span>Shortcuts never spend money on their own: anything paid still goes through Voltage's gate.</span>
          <span className="flex-1" />
          <a href={hrefFor({ page: 'help' })} className="tag text-foreground no-underline hover:underline" onClick={onClose}>All of Help →</a>
        </div>
      </DialogContent>
    </Dialog>
  )
}
