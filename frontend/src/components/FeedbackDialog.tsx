import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { sendBetaFeedback } from '../api'
import { parseRoute } from '../lib/route'
import { lastJobId } from '../lib/lastJob'
import { said } from '../pages/fmt'

/** Rehearsal item 11: "Send feedback" from the help menu (the ? sheet and Help).
 *  Anything can open it with `openFeedback()`; `<FeedbackHost />` (mounted once in App) draws it. */
const EVENT = 'voltage:feedback'
export const openFeedback = () => window.dispatchEvent(new Event(EVENT))

export const APP_VERSION: string = (import.meta.env.VITE_APP_VERSION as string | undefined) || 'dev'
const MAX_SHOT = 5 * 1024 * 1024
const TYPES = ['image/png', 'image/jpeg', 'image/webp']

/** What is attached on its own: where they are, the open video, the last job. */
export function context(hash = window.location.hash) {
  const route = parseRoute(hash)
  const video = route.page === 'editor' || route.page === 'export' ? route.projectId : null
  return { route: hash || '#home', video_id: video, job_id: lastJobId() }
}

export function FeedbackHost() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const on = () => setOpen(true)
    window.addEventListener(EVENT, on)
    return () => window.removeEventListener(EVENT, on)
  }, [])
  return open ? <FeedbackDialog onClose={() => setOpen(false)} /> : null
}

export function FeedbackDialog({ onClose }: { onClose: () => void }) {
  const [message, setMessage] = useState('')
  const [shot, setShot] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [thanks, setThanks] = useState<string | null>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const where = context()

  const pick = (f: File | null) => {
    setError(null)
    if (f && !TYPES.includes(f.type)) { setShot(null); setError('Attach a PNG, JPEG or WebP image.'); return }
    if (f && f.size > MAX_SHOT) { setShot(null); setError('That screenshot is over 5 MB. A smaller one works.'); return }
    setShot(f)
  }
  const send = async () => {
    setBusy(true); setError(null)
    try {
      const r = await sendBetaFeedback({ message: message.trim(), route: where.route, video_id: where.video_id, job_id: where.job_id,
        app_version: APP_VERSION, screenshot: shot })
      setThanks(r.said)
    } catch (e) { setError(said(e, 'That did not send. Try again in a moment.')) } finally { setBusy(false) }
  }
  const attached = [`this page (${where.route})`, where.video_id && `video ${where.video_id}`, where.job_id && `job ${where.job_id}`, 'the app version and your browser'].filter(Boolean).join(', ')
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        showCloseButton={false}
        className="max-h-[calc(100dvh-2rem)] overflow-auto rounded-xl border-[1.5px] border-ink bg-card p-5 text-foreground sm:max-w-[520px] sm:p-7"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
        data-testid="feedback-dialog"
      >
        <DialogTitle ref={title} tabIndex={-1} className="disp text-[26px] font-bold outline-none">Send feedback</DialogTitle>
        {thanks ? (
          <div className="flex flex-col gap-4">
            <p className="m-0" role="status">{thanks}</p>
            <div><button type="button" className="btn volt sm" onClick={onClose}>Close</button></div>
          </div>
        ) : (
          <form className="flex flex-col gap-3.5" onSubmit={(e) => { e.preventDefault(); if (message.trim()) void send() }}>
            <DialogDescription className="m-0 text-sm text-muted-foreground">What worked, what did not, what you expected. We read every message.</DialogDescription>
            <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Message</span>
              <textarea className="min-h-28 rounded-lg border-[1.5px] border-foreground bg-card p-2.5 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-volt" value={message} maxLength={4000} required onChange={(e) => setMessage(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Screenshot <span className="font-normal text-muted-foreground">(optional, PNG, JPEG or WebP, up to 5 MB)</span></span>
              <input type="file" accept="image/png,image/jpeg,image/webp" className="text-sm file:mr-3 file:rounded-md file:border-[1.5px] file:border-foreground file:bg-card file:px-3 file:py-1.5 file:font-semibold" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
            </label>
            <p className="m-0 text-[13px] text-muted-foreground" data-testid="feedback-context">Sent with it: {attached}.</p>
            {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
            <div className="flex flex-wrap justify-end gap-2.5">
              <button type="button" className="btn sm" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn volt sm" disabled={busy || !message.trim()}>{busy ? 'Sending…' : 'Send feedback'}</button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
