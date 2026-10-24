import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import type { BetaQuestion } from '../api'
import { answerBetaSurvey, getBetaSurvey, markBetaSurveyShown } from '../api'
import { useFlags } from '../flags/useFlags'
import { parseRoute } from '../lib/route'
import { cn } from '@/lib/utils'
import { said } from '../pages/fmt'
import { openFeedback } from './FeedbackDialog'

/** Beta kit: three short questions, shown once, after a person's first export.
 *  The Export page calls `exportedNow()` when it shows the file; `<BetaSurveyHost />` (mounted
 *  once in App, for the beta cohort only) asks the server whether they are due, and when they
 *  are, says so (shown) and opens them. Answers go to POST /me/beta-survey. */
const EVENT = 'voltage:exported'
export const exportedNow = () => window.dispatchEvent(new Event(EVENT))

export function BetaSurveyHost({ waitMs = 1500 }: { waitMs?: number }) {
  const beta = useFlags().enabled('beta.cohort')
  const [questions, setQuestions] = useState<BetaQuestion[] | null>(null)
  useEffect(() => {
    if (!beta) return
    let live = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const ask = () => {
      getBetaSurvey().then((s) => {
        if (!live || !s.due) return
        const route = parseRoute(window.location.hash)
        void markBetaSurveyShown(route.page === 'export' ? route.projectId : null).catch(() => { /* shown again next time, at worst */ })
        setQuestions(s.questions)
      }).catch(() => { /* no questions this time */ })
    }
    // The export ticks the checklist a moment later; ask once that has been saved.
    const later = () => { if (timer) clearTimeout(timer); timer = setTimeout(ask, waitMs) }
    ask()
    window.addEventListener(EVENT, later)
    return () => { live = false; if (timer) clearTimeout(timer); window.removeEventListener(EVENT, later) }
  }, [beta, waitMs])
  return questions ? <BetaSurvey questions={questions} onClose={() => setQuestions(null)} /> : null
}

export function BetaSurvey({ questions, onClose }: { questions: BetaQuestion[]; onClose: () => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [thanks, setThanks] = useState<string | null>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const ready = questions.every((q) => q.optional || answers[q.id])
  const send = async () => {
    setBusy(true); setError(null)
    try {
      const route = parseRoute(window.location.hash)
      const r = await answerBetaSurvey({ useful: answers.useful ?? '', almost_stopped: (answers.almost_stopped ?? '').trim(), would_pay: answers.would_pay ?? '',
        video_id: route.page === 'export' || route.page === 'editor' ? route.projectId : null })
      setThanks(r.said)
    } catch (e) { setError(said(e, 'That did not send. Try again in a moment.')) } finally { setBusy(false) }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        showCloseButton={false}
        className="max-h-[calc(100dvh-2rem)] overflow-auto rounded-xl border-[1.5px] border-ink bg-card p-5 text-foreground sm:max-w-[520px] sm:p-7"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
        data-testid="beta-survey"
      >
        <DialogTitle ref={title} tabIndex={-1} className="disp text-[26px] font-bold outline-none">Your first export</DialogTitle>
        {thanks ? (
          <div className="flex flex-col gap-4">
            <p className="m-0" role="status">{thanks}</p>
            <div><button type="button" className="btn volt sm" onClick={onClose}>Close</button></div>
          </div>
        ) : (
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (ready) void send() }}>
            <DialogDescription className="m-0 text-sm text-muted-foreground">Three quick questions, once. They shape what we build next.</DialogDescription>
            {questions.map((q) => q.choices ? (
              <fieldset key={q.id} className="m-0 flex flex-col gap-2 border-0 p-0">
                <legend className="mb-2 p-0 text-[15px] font-semibold">{q.text}</legend>
                <div className="flex flex-wrap gap-2">
                  {q.choices.map(([value, label]) => (
                    <label key={value} className={cn('pill inline-flex min-h-11 cursor-pointer items-center px-3.5 has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50', answers[q.id] === value && 'on')}>
                      <input type="radio" name={q.id} value={value} className="sr-only" checked={answers[q.id] === value} onChange={() => setAnswers((a) => ({ ...a, [q.id]: value }))} />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : (
              <label key={q.id} className="flex flex-col gap-1"><span className="text-[15px] font-semibold">{q.text} {q.optional && <span className="font-normal text-muted-foreground">(optional)</span>}</span>
                <textarea className="min-h-20 rounded-lg border-[1.5px] border-foreground bg-card p-2.5 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-volt" value={answers[q.id] ?? ''} maxLength={2000} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} />
              </label>
            ))}
            {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
            <div className="flex flex-wrap items-center justify-end gap-2.5">
              <button type="button" className="act mr-auto" onClick={() => { onClose(); openFeedback() }}>Something else? Send feedback</button>
              <button type="button" className="btn sm" onClick={onClose}>Not now</button>
              <button type="submit" className="btn volt sm" disabled={busy || !ready}>{busy ? 'Sending…' : 'Send answers'}</button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
