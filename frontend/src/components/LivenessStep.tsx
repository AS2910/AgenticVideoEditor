import { useEffect, useRef, useState } from 'react'
import { sendLiveness, startLiveness } from '../api'
import { said } from '../pages/fmt'

/** G6: consent with liveness. The speaker reads a fresh sentence aloud; the recording is
 *  checked by the liveness provider (fake in this build, test mode) and kept. Record in the
 *  browser, or upload a recording. `onPassed` gets the attempt id the consent cites. */
export function LivenessStep({ videoId, who, onPassed }: { videoId: string; who?: string | null; onPassed: (attemptId: string | null) => void }) {
  const [attempt, setAttempt] = useState<{ id: string; sentence: string; test: boolean } | null>(null)
  const [state, setState] = useState<'idle' | 'recording' | 'checking' | 'passed' | 'failed'>('idle')
  const [note, setNote] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])

  const fresh = async () => {
    setState('idle'); setNote(null); onPassed(null)
    try { const a = await startLiveness(videoId, who); setAttempt({ id: a.attempt_id, sentence: a.sentence, test: a.test_mode }) } catch (e) { setNote(said(e, 'A sentence could not be made. Try again.')) }
  }
  useEffect(() => { void fresh() }, [videoId]) // eslint-disable-line react-hooks/exhaustive-deps

  const check = async (audio: Blob, name: string) => {
    if (!attempt) return
    setState('checking'); setNote(null)
    try {
      const r = await sendLiveness(videoId, attempt.id, audio, name)
      setState(r.status)
      setNote(r.reason)
      onPassed(r.status === 'passed' ? attempt.id : null)
    } catch (e) { setState('failed'); setNote(said(e, 'That recording did not send. Try again.')) }
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
    } catch { setNote('The microphone is not available. Upload a recording of the sentence instead.') }
  }

  return (
    <div className="flex flex-col gap-2.5 rounded-lg bg-sunk p-3" data-testid="liveness">
      <span className="flex flex-wrap items-center gap-2"><span className="tag text-faint">Read this aloud</span>{attempt?.test && <span className="stamp need">Test mode</span>}</span>
      <p className="m-0 text-base font-medium" data-testid="liveness-sentence">{attempt ? `“${attempt.sentence}”` : 'Making a sentence…'}</p>
      <p className="m-0 text-[13px] text-muted-foreground">{who ? `${who} reads` : 'The speaker reads'} it once, so we know they are here and agree. The recording is kept with the consent record.</p>
      <div className="flex flex-wrap items-center gap-2">
        {state === 'recording'
          ? <button type="button" className="btn sm ink" onClick={() => recorder.current?.stop()}>Stop and check</button>
          : state !== 'passed' && <button type="button" className="btn sm" disabled={!attempt || state === 'checking'} onClick={() => void record()}>{state === 'checking' ? 'Checking…' : 'Record'}</button>}
        {state !== 'passed' && state !== 'recording' && (
          <label className="act cursor-pointer">Upload a recording
            <input type="file" accept="audio/*,video/*" className="sr-only" disabled={!attempt || state === 'checking'}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void check(f, f.name); e.target.value = '' }} />
          </label>
        )}
        {state === 'failed' && <button type="button" className="act" onClick={() => void fresh()}>New sentence</button>}
      </div>
      {note && <p className={state === 'passed' ? 'm-0 text-[13px]' : 'm-0 text-[13px] text-needs'} role="status" data-testid="liveness-note">{state === 'passed' ? `Recorded. ${note}` : note}</p>}
    </div>
  )
}
