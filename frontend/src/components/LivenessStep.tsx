import { useEffect, useRef, useState } from 'react'
import type { ConsentAttempt, ConsentStatus } from '../api'
import { sendLiveness, startLiveness } from '../api'
import { said } from '../pages/fmt'
import { Tip } from '../guides/Tip'

type State = 'idle' | 'recording' | 'checking' | ConsentStatus

/** G6: consent with liveness. The speaker reads a fresh sentence aloud; the recording is
 *  checked and kept. Record in the browser, or upload a recording. `onPassed` gets the
 *  attempt id the consent cites.
 *  Run 4 item 2 (`voices.cloning_verified`, the attempt says `verified`): the sentence is a
 *  random phrase, and the check is real: the words heard, the length, and the voice against
 *  the speaker in the video. The result is one of passed, sent for review (a person listens),
 *  or did not pass, with the reason and what to try. Without the flag the check is the
 *  stand-in of G6 (test mode). */
export function LivenessStep({ videoId, who, onPassed }: { videoId: string; who?: string | null; onPassed: (attemptId: string | null) => void }) {
  const [attempt, setAttempt] = useState<ConsentAttempt | null>(null)
  const [state, setState] = useState<State>('idle')
  const [note, setNote] = useState<string | null>(null)
  const [tip, setTip] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const verified = !!attempt?.verified

  const settle = (a: Pick<ConsentAttempt, 'attempt_id' | 'status' | 'reason' | 'tip'>) => {
    setState(a.status === 'waiting' ? 'idle' : a.status)
    setNote(a.reason || null)
    setTip(a.tip || null)
    onPassed(a.status === 'passed' ? a.attempt_id : null)
  }
  const fresh = async (anew = false) => {
    setState('idle'); setNote(null); setTip(null); onPassed(null)
    try {
      const a = await startLiveness(videoId, who, anew)
      setAttempt(a)
      if (a.status && a.status !== 'waiting') settle(a)     // a check of this video already passed, or is with a reviewer
    } catch (e) { setNote(said(e, 'A phrase could not be made. Try again.')) }
  }
  useEffect(() => { void fresh() }, [videoId]) // eslint-disable-line react-hooks/exhaustive-deps

  const check = async (audio: Blob, name: string) => {
    if (!attempt) return
    setState('checking'); setNote(null); setTip(null)
    try {
      const r = await sendLiveness(videoId, attempt.attempt_id, audio, name)
      settle({ ...r, tip: r.tip ?? '' })
    } catch (e) { setState('failed'); setNote(said(e, 'That recording did not send. Try again.')); onPassed(null) }
  }
  const record = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const r = new MediaRecorder(stream)
      chunks.current = []
      r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data) }
      r.onstop = () => { stream.getTracks().forEach((t) => t.stop()); void check(new Blob(chunks.current, { type: r.mimeType || 'audio/webm' }), 'liveness.webm') }
      recorder.current = r
      r.start()
      setState('recording')
    } catch { setNote(`The microphone is not available. Upload a recording of the ${verified ? 'phrase' : 'sentence'} instead.`) }
  }

  // A verified check that has an answer (passed, with a reviewer, did not pass) takes no second
  // recording: its phrase is spent. The stand-in keeps its old controls.
  const done = verified ? state === 'passed' || state === 'review' || state === 'failed' : state === 'passed'
  const word = verified ? 'phrase' : 'sentence'
  const shown = state === 'passed' ? (verified ? `Passed. ${note ?? ''}` : `Recorded. ${note ?? ''}`)
    : verified && state === 'review' ? `Sent for review. ${note ?? ''} You will get a notification when it is decided, then confirm here.`
      : verified && state === 'failed' ? `Did not pass. ${note ?? ''}` : note
  return (
    <div className="flex flex-col gap-2.5 rounded-lg bg-sunk p-3" data-testid="liveness" data-tour="liveness" data-state={state}>
      <Tip id="first-consent-liveness" target="liveness" inline />
      <span className="flex flex-wrap items-center gap-2">
        <span className="tag text-faint">Read this aloud</span>
        {attempt?.test_mode && <span className="stamp need">Test mode</span>}
        {verified && state === 'passed' && <span className="stamp">Passed</span>}
        {verified && state === 'review' && <span className="stamp need">Sent for review</span>}
        {verified && state === 'failed' && <span className="stamp inkd">Did not pass</span>}
      </span>
      <p className="m-0 text-base font-medium" data-testid="liveness-sentence">{attempt ? `“${attempt.sentence}”` : `Making a ${word}…`}</p>
      <p className="m-0 text-[13px] text-muted-foreground">
        {verified
          ? `${who ? `${who} reads` : 'The speaker reads'} the phrase once, in their own voice, at an easy pace. We check the words, and compare the voice with the speaker in the video. The recording is kept with the consent record.`
          : `${who ? `${who} reads` : 'The speaker reads'} it once, so we know they are here and agree. The recording is kept with the consent record.`}
      </p>
      {!done && (
        <div className="flex flex-wrap items-center gap-2">
          {state === 'recording'
            ? <button type="button" className="btn sm ink" onClick={() => recorder.current?.stop()}>Stop and check</button>
            : <button type="button" className="btn sm" disabled={!attempt || state === 'checking'} onClick={() => void record()}>{state === 'checking' ? 'Checking…' : 'Record'}</button>}
          {state !== 'recording' && (
            <label className="act cursor-pointer">Upload a recording
              <input type="file" accept="audio/*,video/*" className="sr-only" disabled={!attempt || state === 'checking'}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void check(f, f.name); e.target.value = '' }} />
            </label>
          )}
          {state === 'failed' && <button type="button" className="act" onClick={() => void fresh()}>New sentence</button>}
        </div>
      )}
      {shown && <p className={state === 'passed' || state === 'review' ? 'm-0 text-[13px]' : 'm-0 text-[13px] text-needs'} role="status" data-testid="liveness-note">{shown}</p>}
      {verified && state === 'failed' && tip && <p className="m-0 text-[13px] text-muted-foreground" data-testid="liveness-tip">{tip}</p>}
      {verified && (state === 'failed' || state === 'review') && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn sm" onClick={() => void fresh(true)}>{state === 'review' ? `Read a new ${word} instead` : `Read a new ${word}`}</button>
        </div>
      )}
    </div>
  )
}
