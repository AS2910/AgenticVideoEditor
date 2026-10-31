import { useState } from 'react'
import { NoGoHoldsQueue } from './NoGoHoldsQueue'
import { NoGoVoicesList } from './NoGoVoicesList'

/** Voice consent V1: the Voice safety tab. Step 5 adds the borderline no-go queue and the
 *  no-go list; step 4's held lines and the own-voice checks are its other queues (merge
 *  them in here as sibling parts). */
export function VoiceSafetySection({ card }: { card: string }) {
  const [n, setN] = useState(0)          // the list changed: the queue may have lost items (a removed voice closes them)
  return (
    <section className={`${card} flex flex-col gap-5`} aria-labelledby="voice-safety-h" data-testid="admin-voice-safety">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="voice-safety-h" className="disp m-0 text-[22px] font-bold">Voice safety</h2>
        <span className="tag text-faint">what waits for a person, and the voices Voltage does not clone</span>
      </div>
      <NoGoHoldsQueue key={n} />
      <NoGoVoicesList onChange={() => setN((x) => x + 1)} />
    </section>
  )
}
