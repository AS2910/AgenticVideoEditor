import { useEffect, useRef, useState } from 'react'
import type { Usage } from '../types'
import styles from './SpendMeter.module.css'

const VENDORS: Record<string, string> = {
  openai: 'Transcription', elevenlabs: 'Voice', anthropic: 'Reading requests',
}

/** The project's spend against its cap, as a small meter (UX-3). The meter is
 *  a button: its breakdown — each vendor's line, voice characters against
 *  their ceiling, and with sign-in on the person's spend across projects —
 *  opens as a popover (the polish pass, from UX-6's list), so it is there for
 *  touch and keyboard, not only under a hover. Escape or a click outside
 *  closes it and focus returns to the meter. */
export function SpendMeter({ usage }: { usage: Usage | null }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const meter = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      setOpen(false)
      meter.current?.focus()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  if (!usage) return null
  const share = usage.ceiling_usd > 0 ? Math.min(1, usage.spent_usd / usage.ceiling_usd) : 0
  const near = share >= 0.8
  const spent = `$${usage.spent_usd.toFixed(2)} of $${usage.ceiling_usd.toFixed(2)}`
  const across = usage.user_spent_usd != null && usage.user_ceiling_usd != null
  return (
    <div ref={root} className={styles.wrap}>
      <button
        ref={meter}
        type="button"
        className={near ? styles.near : styles.meter}
        data-testid="spend"
        aria-expanded={open}
        aria-controls="spend-breakdown"
        aria-label={`Spent ${spent} on this project${near ? ', near the cap' : ''}. ${open ? 'Hide' : 'Show'} the breakdown`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={styles.label}>{spent}</span>
        {near && <span className={styles.nearWord} role="status">near the cap</span>}
        <span
          className={styles.track}
          role="meter"
          aria-label="Spend against the cap"
          aria-valuemin={0}
          aria-valuemax={usage.ceiling_usd}
          aria-valuenow={usage.spent_usd}
        ><span className={styles.fill} style={{ transform: `scaleX(${share})` }} /></span>
        {' '}
        <span className={styles.detail}>{usage.voice_characters.toLocaleString()} of {usage.voice_characters_ceiling.toLocaleString()} voice characters</span>
      </button>
      {open && (
        <div id="spend-breakdown" className={styles.pop} role="dialog" aria-label="Spend breakdown" data-testid="spend-breakdown">
          <dl className={styles.rows}>
            {usage.lines.map((l) => (
              <div key={`${l.vendor}-${l.what}-${l.unit}`} className={styles.row}>
                <dt>{VENDORS[l.vendor] ?? l.vendor}</dt>
                <dd>${l.usd.toFixed(3)} <span className={styles.calls}>· {l.calls} {l.calls === 1 ? 'call' : 'calls'}</span></dd>
              </div>
            ))}
            {usage.lines.length === 0 && <div className={styles.row}><dt>Nothing spent yet</dt><dd>$0.000</dd></div>}
            <div className={styles.row}>
              <dt>Voice characters</dt>
              <dd>{usage.voice_characters.toLocaleString()} <span className={styles.calls}>of {usage.voice_characters_ceiling.toLocaleString()}</span></dd>
            </div>
            {across && (
              <div className={styles.row}>
                <dt>You, across projects</dt>
                <dd>${usage.user_spent_usd!.toFixed(2)} <span className={styles.calls}>of ${usage.user_ceiling_usd!.toFixed(2)}</span></dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </div>
  )
}
