import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { ProjectRule } from '../types'
import { addRule, uploadRuleAudio } from '../api'
import { termOf } from '../lib/words'

const inputClass = 'h-8 w-full rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

interface Spot { term: string; left: number; top: number }

/** A3, learn a word: select a word in the transcript and "Add to project
 *  words" offers itself beside it; the form takes how it is said, an
 *  optional respelling and an optional short clip of it said right. */
export function LearnWord({ projectId, projectName, container = '[data-testid="transcript-list"]', onAdded }: {
  projectId: string; projectName?: string | null; container?: string; onAdded?: (rule: ProjectRule) => void
}) {
  const [spot, setSpot] = useState<Spot | null>(null)
  const [form, setForm] = useState<{ term: string; say: string; respell: string; clip: File | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const formOpen = form !== null

  useEffect(() => {
    const read = (e: Event) => {
      if (formOpen || (e.target instanceof Node && card.current?.contains(e.target))) return
      const sel = window.getSelection()
      const inside = (n: Node | null) => !!n && !!(n instanceof Element ? n : n.parentElement)?.closest(container)
      // isCollapsed is not trusted: Chrome reports a double-clicked word as collapsed; the text is what counts.
      if (!sel || sel.rangeCount === 0 || !sel.toString().trim() || !inside(sel.anchorNode) || !inside(sel.focusNode)) { setSpot(null); return }
      const term = termOf(sel.toString())
      if (!term) { setSpot(null); return }
      const range = sel.getRangeAt(0)
      const box = typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : { left: 16, bottom: 16 }
      const left = Math.max(16, Math.min(window.innerWidth - 336, box.left))
      setSpot({ term, left, top: Math.min(window.innerHeight - 60, box.bottom + 8) })
      setDone(null)
    }
    document.addEventListener('mouseup', read)
    document.addEventListener('keyup', read)
    return () => { document.removeEventListener('mouseup', read); document.removeEventListener('keyup', read) }
  }, [container, formOpen])
  useEffect(() => {
    if (!spot && !done) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { setSpot(null); setForm(null); setDone(null) } }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [spot, done])
  useEffect(() => {
    if (!done) return
    const t = window.setTimeout(() => setDone(null), 4000)
    return () => window.clearTimeout(t)
  }, [done])

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!form || !form.term.trim() || !form.say.trim()) return
    setBusy(true)
    setError(null)
    try {
      let rule = await addRule(projectId, 'pronounce', { term: form.term.trim(), say: form.say.trim(), ...(form.respell.trim() ? { respell: form.respell.trim() } : {}) }, 'transcript')
      if (form.clip) rule = await uploadRuleAudio(projectId, rule.rule_id, form.clip)
      onAdded?.(rule)
      setDone(`Added “${rule.data.term}” to ${projectName ?? 'the project'}'s words.`)
      setForm(null)
      setSpot(null)
      window.getSelection()?.removeAllRanges()
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Could not add the word.')
    } finally { setBusy(false) }
  }

  if (done && !spot) {
    return <div className="rise fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-xl bg-ink px-4 py-3 text-sm text-ptext" role="status">{done}</div>
  }
  if (!spot) return null
  return (
    <div ref={card} className="rise fixed z-40 flex w-80 max-w-[calc(100vw-32px)] flex-col gap-2 rounded-xl border-[1.5px] border-ink bg-card p-2.5 shadow-volt" style={{ left: spot.left, top: spot.top }} data-testid="learn-word">
      {!form ? (
        <button type="button" className="btn sm self-start" onMouseDown={(e) => e.preventDefault()} onClick={() => setForm({ term: spot.term, say: '', respell: '', clip: null })}>
          Add to project words
        </button>
      ) : (
        <form className="flex flex-col gap-2" onSubmit={(e) => void save(e)} aria-label="Add to project words">
          <span className="tag text-faint">Add to {projectName ?? 'project'} words</span>
          <label className="flex flex-col gap-1 text-[13px]">Term<input className={inputClass} value={form.term} onChange={(e) => setForm({ ...form, term: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-[13px]">How to say it<input className={inputClass} value={form.say} placeholder="e.g. BAH-jee cam" autoFocus onChange={(e) => setForm({ ...form, say: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-[13px]">Respell (optional)<input className={inputClass} value={form.respell} placeholder="What the voice is sent" onChange={(e) => setForm({ ...form, respell: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-[13px]">A short clip of it said right (optional)
            <input className="text-[13px]" type="file" accept="audio/*,video/webm" onChange={(e) => setForm({ ...form, clip: e.target.files?.[0] ?? null })} />
          </label>
          {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
          <div className="flex items-center gap-2">
            <button type="button" className="act" onClick={() => { setForm(null); setSpot(null) }}>Cancel</button>
            <span className="flex-1" />
            <button type="submit" className="btn volt sm" disabled={busy || !form.term.trim() || !form.say.trim()}>{busy ? 'Adding…' : 'Add word'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
