import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Pause, Play } from 'lucide-react'
import { cn } from '@/lib/utils'

/** A mark on the scrubber: a proposal (volt), a line in the video (ink), a step waiting on you (warn). */
export interface Marker { at: number; tone: 'volt' | 'ink' | 'warn'; label: string }

interface PlayerProps {
  src: string
  duration: number
  currentTime: number
  onSeek: (t: number) => void
  /** Called as the video plays, with its own clock. */
  onTimeUpdate?: (t: number) => void
  /** A seek asked for from outside (e.g. the transcript). `id` makes asking
   *  for the same time twice still move the video. With `play`, playback
   *  starts there; with `until`, it stops at that moment. With `stop`, the
   *  video only pauses where it is. */
  seekRequest?: { time: number; id: number; play?: boolean; until?: number; stop?: boolean } | null
  onPlayingChange?: (playing: boolean) => void
  /** The line being said at the playhead, shown over the picture. */
  caption?: ReactNode
  /** The original's sound off while a replacement take plays over it. */
  muted?: boolean
  /** Volt: what the player plays, as a tag on the picture ("With proposals"). */
  badge?: string
  /** Volt: a 2 px line sweeps the picture while Voltage reads or looks; the words beside it say what it is doing. */
  scanning?: string | null
  /** Volt: marks on the scrubber. */
  markers?: Marker[]
  /** Shown at the end of the transport row (the Tracks toggle, the word timeline). */
  children?: ReactNode
  /** Volt: a large play button on the picture, for the first read. */
  bigPlay?: boolean
  /** As shot (2026-10-19): where the next file should start, when its clock differs from this one's
   *  (a retimed render). `id` makes a repeat ask count. Without it the new file starts where this one was. */
  carry?: { time: number; id: number } | null
}

/** play() returns a promise in browsers and nothing in jsdom; neither may throw. */
const playSafely = (video: HTMLVideoElement) => {
  const p = video.play() as Promise<void> | undefined
  if (p && typeof p.catch === 'function') p.catch(() => {})
}

/** m:ss.c — tenths on the scrubber, as the mocks show. */
export const timecode = (t: number) => {
  const safe = Math.max(0, t)
  const m = Math.floor(safe / 60)
  const s = (safe - m * 60).toFixed(1).padStart(4, '0')
  return `${m}:${s}`
}

/** The picture and its scrubber (Volt, 2026-10-18): the video on a near-black
 *  stage with an ink border, the mode tag and the clock on it, the caption
 *  strip, then a transport row — an ink play button, the mono clock, the
 *  scrubber with its markers and playhead, and whatever the caller puts on
 *  the right (Tracks, the word timeline). */
export function Player({
  src, duration, currentTime, onSeek, onTimeUpdate, seekRequest, caption, children, muted, onPlayingChange, badge, scanning, markers = [], bigPlay, carry,
}: PlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  // The playing file's own length: an edit that adds a line makes the render
  // longer than the source `duration` describes.
  const [length, setLength] = useState(duration)

  // A new file (a finished render, or another mode) resumes at the moment the old one was at, and keeps
  // playing if it was playing — so Edited ↔ As shot is an instant comparison. The URL carries the
  // artifact's sha, so a new render is always a new file.
  const lastTime = useRef(0)
  const resumeAt = useRef<number | null>(null)
  const playingNow = useRef(false)
  const resumePlay = useRef(false)
  const carried = useRef<number | null>(null)
  useEffect(() => { playingNow.current = playing }, [playing])
  useEffect(() => {
    resumePlay.current = playingNow.current
    const fresh = carry && carry.id !== carried.current ? carry : null
    if (fresh) carried.current = fresh.id
    resumeAt.current = fresh ? fresh.time : lastTime.current
    setPlaying(false)
    setLength(duration)
    console.debug('[player] load', { src: src.split('/').pop()?.slice(0, 12), at: Number((resumeAt.current ?? 0).toFixed(2)), play: resumePlay.current })
    // carry is read with the file it belongs to; a carry alone does not reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, duration])

  useEffect(() => { onPlayingChange?.(playing) }, [playing, onPlayingChange])

  const stopAt = useRef<number | null>(null)
  useEffect(() => {
    const video = videoRef.current
    if (!seekRequest || !video) return
    if (seekRequest.stop) {
      stopAt.current = null
      video.pause()
      setPlaying(false)
      return
    }
    video.currentTime = seekRequest.time
    lastTime.current = seekRequest.time
    stopAt.current = seekRequest.until ?? null
    if (seekRequest.play) {
      playSafely(video)
      setPlaying(true)
    }
  }, [seekRequest])

  const toggle = () => {
    const video = videoRef.current
    if (video) {
      if (playing) video.pause()
      else playSafely(video)
    }
    setPlaying((p) => !p)
  }

  const seek = (t: number) => {
    lastTime.current = t
    if (videoRef.current) videoRef.current.currentTime = t
    onSeek(t)
  }

  const pct = (t: number) => `${length > 0 ? Math.min(100, Math.max(0, (t / length) * 100)) : 0}%`
  const head = length > 0 ? Math.min(100, (currentTime / length) * 100) : 0
  const TONE: Record<Marker['tone'], string> = {
    volt: 'bg-volt border-ink', ink: 'bg-foreground border-foreground', warn: 'bg-warn border-ink',
  }
  return (
    <section className="mx-auto flex w-full max-w-[720px] flex-col gap-3.5" aria-label="Monitor">
      <div className="relative aspect-video w-full overflow-hidden rounded-xl border-[1.5px] border-ink bg-pic">
        <video
          ref={videoRef}
          className="absolute inset-0 size-full bg-pic object-contain"
          src={src}
          muted={muted}
          playsInline
          onLoadedMetadata={(e) => {
            const d = e.currentTarget.duration
            if (Number.isFinite(d) && d > 0) setLength(d)
            const at = resumeAt.current
            resumeAt.current = null
            if (at !== null && at > 0) {
              const t = Number.isFinite(d) && d > 0 ? Math.min(at, Math.max(0, d - 0.05)) : at
              e.currentTarget.currentTime = t
              lastTime.current = t
              onTimeUpdate?.(t)
            }
            if (resumePlay.current) {
              resumePlay.current = false
              playSafely(e.currentTarget)
              setPlaying(true)
            }
          }}
          onTimeUpdate={(e) => {
            const t = e.currentTarget.currentTime
            lastTime.current = t
            onTimeUpdate?.(t)
            if (stopAt.current !== null && t >= stopAt.current) {
              stopAt.current = null
              e.currentTarget.pause()
              setPlaying(false)
            }
          }}
          onEnded={() => setPlaying(false)}
        />
        {badge && (
          <span className="tag absolute top-3.5 left-3.5 inline-flex items-center gap-1.5 rounded-[5px] bg-ink/60 px-2 py-1 text-volt" data-testid="mode-badge">
            <span className="blinkdot size-[7px] rounded-full bg-volt" aria-hidden="true" />{badge}
          </span>
        )}
        <span className="tnum absolute top-3.5 right-3.5 rounded-[5px] bg-ink/60 px-2 py-1 text-xs text-ptext" aria-hidden="true">{timecode(currentTime)}</span>
        {scanning && (
          <>
            <span className="tag absolute top-3.5 right-3.5 translate-y-8 rounded-[5px] bg-warn px-2 py-1 text-ink" role="status">{scanning}</span>
            <span className="scan absolute inset-y-0 left-0 w-0.5 bg-warn opacity-85" aria-hidden="true" data-testid="scan" />
          </>
        )}
        {bigPlay && !playing && (
          <button type="button" className="btn volt absolute top-1/2 left-1/2 size-14 -translate-x-1/2 -translate-y-1/2 rounded-full p-0" aria-label="Play" onClick={toggle}>
            <Play fill="currentColor" aria-hidden="true" />
          </button>
        )}
        {/* The line at the playhead, as the picture shows it, once the picture moves. */}
        {caption && (playing || currentTime > 0) && <div
          className={cn(
            'absolute inset-x-6 bottom-5 z-10 text-center',
            '[&_ins]:rounded-sm [&_ins]:bg-volt [&_ins]:px-1 [&_ins]:text-ink [&_ins]:no-underline',
            '[&_ins:not([data-said]):has(~ins[data-said])]:bg-transparent [&_ins:not([data-said]):has(~ins[data-said])]:text-pmuted [&_ins[data-said]~ins:not([data-said])]:bg-transparent [&_ins[data-said]~ins:not([data-said])]:text-pmuted',
          )}
          data-testid="caption"
          aria-hidden="true"
        ><span className="inline-block max-w-full truncate rounded-md bg-ink/70 px-3 py-1.5 text-base text-ptext">{caption}</span></div>}
      </div>
      <div className="flex items-center gap-3.5">
        <button type="button" className="btn ink sm w-9 shrink-0 p-0" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause size={14} fill="currentColor" aria-hidden="true" /> : <Play size={14} fill="currentColor" aria-hidden="true" />}
        </button>
        <span className="tnum text-[13px] whitespace-nowrap" data-testid="timecode">
          {timecode(currentTime)} <span className="text-faint">/ {timecode(length)}</span>
        </span>
        {/* The scrubber: a hairline track, the played part in ink, markers, the playhead,
            and the real range input laid invisibly over it so it stays a slider. */}
        <div className="relative h-7 min-w-0 flex-1">
          <div className="absolute inset-x-0 top-3 h-1 rounded-sm bg-line" aria-hidden="true" />
          <div className="absolute top-3 left-0 h-1 rounded-sm bg-foreground" style={{ width: `${head}%` }} aria-hidden="true" />
          {markers.filter((m) => m.at >= 0 && m.at <= length).map((m, i) => (
            <span
              key={i}
              className={cn('pointer-events-none absolute -ml-[5px] rounded-[3px] border-[1.5px]', TONE[m.tone], m.tone === 'ink' ? 'top-[9px] h-2.5 w-1.5 -ml-[3px]' : 'top-[7px] h-3.5 w-2.5')}
              data-testid="marker"
              data-tone={m.tone}
              title={m.label}
              style={{ left: pct(m.at) }}
            />
          ))}
          <span className="pointer-events-none absolute inset-y-0 z-20 -ml-px w-0.5 bg-foreground" data-testid="head" style={{ left: `${head}%` }} />
          <input
            className="absolute inset-0 z-20 m-0 size-full cursor-pointer opacity-0 focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50"
            type="range"
            min={0}
            max={length}
            step={0.01}
            value={Math.min(currentTime, length)}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
            aria-valuetext={`${timecode(currentTime)} of ${timecode(length)}`}
          />
        </div>
        {children}
      </div>
    </section>
  )
}
