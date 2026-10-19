import { useId, useState } from 'react'
import type { Beat, Understanding } from '../types'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'

/** 2026-10-20: what Voltage sees in the video, as a piece. A collapsible
 *  card at the top of the pane: the kind of piece and a one-line summary,
 *  the beats (a click seeks), the style line to use or change, and a way to
 *  correct the read. Corrections win over Voltage's own read in every turn. */
export interface WhatISeeProps {
  seen: Understanding
  onSeek: (t: number) => void
  onCorrect: (change: { text: string; beat_at?: number; remove?: boolean }) => Promise<unknown> | void
  onStyle: (line: string) => Promise<unknown> | void
  defaultOpen?: boolean
  disabled?: boolean
}

const time = (t: number) => `${clock(t)}.${Math.floor((t % 1) * 10)}`

export function WhatISee({ seen, onSeek, onCorrect, onStyle, defaultOpen = true, disabled }: WhatISeeProps) {
  const id = useId()
  const [open, setOpen] = useState(defaultOpen)
  const [fixing, setFixing] = useState(false)
  const [words, setWords] = useState('')
  const [styling, setStyling] = useState(false)
  const [line, setLine] = useState(seen.style?.line ?? '')
  const read = seen.read ?? {}
  const kind = [read.format, read.genre].filter(Boolean).join(' · ')
  const beats = seen.beats.filter((b) => b.kind !== 'cut')
  const cuts = seen.beats.length - beats.length
  const style = seen.style
  const send = async () => {
    const text = words.trim()
    if (!text) return
    await onCorrect({ text })
    setWords('')
    setFixing(false)
  }
  const sure = (b: Beat) => b.source === 'user' || b.confidence >= 0.6
  return (
    <section className="rounded-[10px] border-[1.5px] border-pline bg-psunk" aria-labelledby={`${id}-h`} data-testid="what-i-see">
      <h3 id={`${id}-h`} className="m-0">
        <button type="button" className="flex min-h-11 w-full min-w-0 items-center gap-2 px-3.5 py-2 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          aria-expanded={open} aria-controls={`${id}-b`} onClick={() => setOpen((o) => !o)}>
          <span className="tag shrink-0">What I see</span>
          <span className="min-w-0 truncate text-sm text-ptext">{kind || 'Reading the picture and the sound'}</span>
          <span className="ml-auto shrink-0 pm" aria-hidden="true">{open ? '▴' : '▾'}</span>
        </button>
      </h3>
      {open && (
        <div id={`${id}-b`} className="flex min-w-0 flex-col gap-2.5 px-3.5 pb-3.5">
          {read.summary && <p className="m-0 text-[15px] [overflow-wrap:anywhere]">{read.summary}</p>}
          {beats.length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0" aria-label="Beats">
              {beats.map((b) => (
                <li key={`${b.at}-${b.label}`} className="flex min-w-0 items-center gap-1">
                  <button type="button" className="act min-w-0 flex-1 justify-start" onClick={() => onSeek(b.at)} aria-label={`Go to ${time(b.at)}: ${b.label}`}>
                    <span className="tnum shrink-0 pm">{time(b.at)}</span>
                    <span className={cn('min-w-0 truncate', !sure(b) && 'pm')}>{b.label}{!sure(b) && ' ?'}{b.source === 'user' && ' (yours)'}</span>
                  </button>
                  {b.source !== 'user' && (
                    <button type="button" className="act shrink-0 text-xs" disabled={disabled}
                      onClick={() => void onCorrect({ text: `Not ${b.label} at ${time(b.at)}`, beat_at: b.at, remove: true })}
                      aria-label={`Not right: ${b.label} at ${time(b.at)}`}>Not right</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {cuts > 0 && <span className="tag pm">{cuts} {cuts === 1 ? 'cut' : 'cuts'}</span>}
          {seen.corrections.length > 0 && (
            <p className="m-0 text-sm pm" data-testid="corrections">You said: {seen.corrections.map((c) => c.text).filter(Boolean).join(' · ')}</p>
          )}
          {style?.line && (
            <div className="flex min-w-0 flex-col gap-1.5 border-t border-pline pt-2.5" data-testid="style">
              <span className="tag">Style {style.accepted ? '' : '· proposed'}</span>
              {styling ? (
                <div className="flex min-w-0 flex-col gap-2">
                  <label htmlFor={`${id}-style`} className="sr-only">How the new words should sound</label>
                  <textarea id={`${id}-style`} rows={2} className="w-full resize-none rounded-md border border-pline bg-pane p-2 text-sm" value={line} onChange={(e) => setLine(e.target.value)} />
                  <span className="flex gap-2">
                    <button type="button" className="btn volt sm" disabled={disabled || !line.trim()} onClick={() => { void onStyle(line.trim()); setStyling(false) }}>Save style</button>
                    <button type="button" className="act" onClick={() => { setLine(style.line); setStyling(false) }}>Cancel</button>
                  </span>
                </div>
              ) : (
                <>
                  <p className="m-0 text-sm [overflow-wrap:anywhere]">{style.line}</p>
                  <span className="-ml-2 flex flex-wrap gap-1">
                    {!style.accepted && <button type="button" className="act" disabled={disabled} onClick={() => void onStyle(style.line)}>Use it</button>}
                    <button type="button" className="act" onClick={() => { setLine(style.line); setStyling(true) }}>Change it</button>
                  </span>
                </>
              )}
            </div>
          )}
          {fixing ? (
            <div className="flex min-w-0 flex-col gap-2">
              <label htmlFor={`${id}-fix`} className="text-sm pm">What did Voltage get wrong?</label>
              <input id={`${id}-fix`} className="h-11 w-full rounded-md border border-pline bg-pane px-2.5 text-sm" placeholder="This is Muay Thai" value={words}
                onChange={(e) => setWords(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void send() } if (e.key === 'Escape') setFixing(false) }} />
              <span className="flex gap-2">
                <button type="button" className="btn sm" disabled={disabled || !words.trim()} onClick={() => void send()}>Correct it</button>
                <button type="button" className="act" onClick={() => setFixing(false)}>Cancel</button>
              </span>
            </div>
          ) : (
            <span className="-ml-2 flex"><button type="button" className="act" onClick={() => setFixing(true)}>Correct it</button></span>
          )}
        </div>
      )}
    </section>
  )
}
