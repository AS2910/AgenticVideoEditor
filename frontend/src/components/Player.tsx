import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Word } from '../types'
import { rulerMarks } from '../timeline/ruler'
import { Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** The monitor (UX-7b): the picture at 16:9 across the column, the line being
 *  said captioned over it, the transport under it, and the timeline: the
 *  lines as blocks by speaker, the changes marked, the words as ticks, a
 *  playhead and a ruler. */

const TONES: Record<Block['tone'], string> = {
  a: 'border-spk-a bg-spk-a/25',
  b: 'border-spk-b bg-spk-b/25',
  c: 'border-spk-c bg-spk-c/25',
  d: 'border-spk-d bg-spk-d/25',
  x: 'border-muted-foreground bg-muted-foreground/25',
  changed: 'z-10 border-changed bg-changed-soft',
}

/** A span on the monitor's timeline: who speaks it, or that it changed. */
export interface Block { start: number; end: number; tone: 'a' | 'b' | 'c' | 'd' | 'x' | 'changed' }

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
   *  video only pauses where it is (a row's Stop button). */
  seekRequest?: { time: number; id: number; play?: boolean; until?: number; stop?: boolean } | null
  /** Told whenever the video starts or stops, so a row elsewhere can say
   *  Stop while its seam plays and go quiet when it ends. */
  onPlayingChange?: (playing: boolean) => void
  /** The lines on the timeline, coloured by speaker, and the spans that changed (UX-7b). */
  blocks?: Block[]
  /** The words, as ticks along the foot of the timeline. */
  words?: Word[]
  /** The line being said at the playhead, shown over the picture. */
  caption?: ReactNode
  /** Shown at the end of the transport row (e.g. the Edited / Original switch). */
  children?: ReactNode
  /** The original's sound off while a replacement take plays over it. */
  muted?: boolean
  /** A take being placed: a block of its length on the bar, draggable. */
  placing?: { start: number; duration: number } | null
  onPlace?: (start: number) => void
}

/** play() returns a promise in browsers and nothing in jsdom; neither may throw. */
const playSafely = (video: HTMLVideoElement) => {
  const p = video.play() as Promise<void> | undefined
  if (p && typeof p.catch === 'function') p.catch(() => {})
}

/** m:ss.cc — hundredths, because edits land between words. */
const timecode = (t: number) => {
  const safe = Math.max(0, t)
  const m = Math.floor(safe / 60)
  const s = (safe - m * 60).toFixed(2).padStart(5, '0')
  return `${m}:${s}`
}

export function Player({
  src, duration, currentTime, onSeek, onTimeUpdate, seekRequest, blocks = [], words = [], caption, children, muted, placing, onPlace, onPlayingChange,
}: PlayerProps) {
  const barRef = useRef<HTMLDivElement>(null)

  // Drag the block along the bar; the pointer's offset inside it is kept.
  const startPlacing = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!placing || !onPlace || !barRef.current) return
    e.preventDefault()
    const rect = barRef.current.getBoundingClientRect()
    const grabbed = (e.clientX - rect.left) / rect.width * length - placing.start
    const move = (ev: PointerEvent) => {
      const t = (ev.clientX - rect.left) / rect.width * length - grabbed
      onPlace(Math.round(Math.min(Math.max(0, t), Math.max(0, length - placing.duration)) * 100) / 100)
    }
    const end = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
  }
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  // The playing file's own length: an edit that adds a line makes the render
  // longer than the source `duration` describes.
  const [length, setLength] = useState(duration)

  // A new file (original ↔ edited) starts paused from its beginning.
  useEffect(() => {
    setPlaying(false)
    setLength(duration)
  }, [src, duration])

  // Whoever asked for a seam or a take to play hears when it has stopped.
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
    if (videoRef.current) videoRef.current.currentTime = t
    onSeek(t)
  }

  const pct = (t: number) => `${length > 0 ? Math.min(100, Math.max(0, (t / length) * 100)) : 0}%`
  const head = length > 0 ? Math.min(100, (currentTime / length) * 100) : 0
  return (
    <section className="flex flex-col gap-3 rounded-lg border bg-card p-2.5 shadow-xs" aria-label="Monitor">
      {/* Neutral black surround so the picture reads true; the column's full
          width, held to the viewport so the script stays in reach. */}
      <div className="relative aspect-video max-h-[56dvh] w-full overflow-hidden rounded-lg bg-monitor">
        <video
          ref={videoRef}
          // Pinned to the stage rather than sized by percentage: `height: 100%`
          // does not resolve against an aspect-ratio box.
          className="absolute inset-0 size-full bg-monitor object-contain"
          src={src}
          muted={muted}
          playsInline
          onLoadedMetadata={(e) => {
            const d = e.currentTarget.duration
            if (Number.isFinite(d) && d > 0) setLength(d)
          }}
          onTimeUpdate={(e) => {
            const t = e.currentTarget.currentTime
            onTimeUpdate?.(t)
            if (stopAt.current !== null && t >= stopAt.current) {
              stopAt.current = null
              e.currentTarget.pause()
              setPlaying(false)
            }
          }}
          onEnded={() => setPlaying(false)}
        />
        {/* The line at the playhead, as the picture shows it, once the picture
            moves. The transcript carries the same words, so this is not read
            out as it changes. */}
        {caption && (playing || currentTime > 0) && <div
          className={cn(
            'absolute bottom-2.5 left-1/2 z-10 max-w-[92%] -translate-x-1/2 truncate rounded-md border bg-background/90 px-3 py-1.5 text-center text-sm whitespace-nowrap text-foreground shadow-sm sm:bottom-4 sm:max-w-[78%] sm:text-base',
            // An added word is marked; a take's words light up as they are said, the ones still to come wait, dimmer.
            '[&_ins]:rounded-sm [&_ins]:bg-changed-soft [&_ins]:px-1 [&_ins]:text-changed [&_ins]:no-underline',
            '[&_ins:not([data-said]):has(~ins[data-said])]:bg-transparent [&_ins:not([data-said]):has(~ins[data-said])]:text-muted-foreground [&_ins[data-said]~ins:not([data-said])]:bg-transparent [&_ins[data-said]~ins:not([data-said])]:text-muted-foreground',
          )}
          data-testid="caption"
          aria-hidden="true"
        >{caption}</div>}
      </div>
      <div className="flex flex-col gap-2 px-1">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="icon" className="rounded-full" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause fill="currentColor" aria-hidden="true" /> : <Play fill="currentColor" aria-hidden="true" />}
          </Button>
          <span className="tnum text-sm whitespace-nowrap" data-testid="timecode">
            {timecode(currentTime)} <span className="text-muted-foreground">/ {timecode(length)}</span>
          </span>
          {children}
        </div>
        {/* The timeline: the lines as blocks, the changes lit, the words as
            ticks, the playhead, and the real range input laid invisibly over
            it all so it stays a slider. */}
        <div className="relative h-10 overflow-hidden rounded-md bg-muted" ref={barRef}>
          {blocks.filter((b) => b.end > 0 && b.start < length).map((b, i) => (
            <span
              key={i}
              className={cn('pointer-events-none absolute top-2.5 h-5 rounded-sm border-l-2', TONES[b.tone])}
              data-tone={b.tone}
              data-testid="block"
              style={{ left: pct(b.start), width: `${Math.max(0.4, ((Math.min(b.end, length) - Math.max(0, b.start)) / Math.max(length, 0.001)) * 100)}%` }}
            />
          ))}
          {words.filter((w) => w.start >= 0 && w.start <= length).map((w, i) => (
            <span key={i} className="pointer-events-none absolute bottom-1 h-1.5 w-px bg-muted-foreground/60" data-testid="tick" style={{ left: pct(w.start) }} />
          ))}
          {placing && length > 0 && (
            <div
              className="absolute top-1.5 z-30 h-7 cursor-grab touch-none rounded-md border border-changed bg-changed-soft shadow-sm outline-none before:absolute before:inset-x-0 before:-inset-y-3.5 before:content-[''] focus-visible:ring-[3px] focus-visible:ring-ring/50 active:cursor-grabbing"
              data-testid="placing"
              role="slider"
              aria-label="Where the take starts"
              aria-valuemin={0}
              aria-valuemax={length}
              aria-valuenow={placing.start}
              aria-valuetext={`${placing.start.toFixed(2)} seconds`}
              tabIndex={0}
              style={{ left: `${(placing.start / length) * 100}%`, width: `${Math.max(0.5, (placing.duration / length) * 100)}%` }}
              onPointerDown={startPlacing}
              onKeyDown={(e) => {
                if (!onPlace) return
                if (e.key === 'ArrowLeft') onPlace(Math.max(0, placing.start - (e.shiftKey ? 1 : 0.1)))
                if (e.key === 'ArrowRight') onPlace(Math.min(length - placing.duration, placing.start + (e.shiftKey ? 1 : 0.1)))
              }}
            />
          )}
          <span className="pointer-events-none absolute inset-y-0 z-20 -ml-px w-0.5 bg-foreground" data-testid="head" style={{ left: `${head}%` }} />
          <input
            // Invisible over the track, but a keyboard user sees it focused.
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
        <div className="relative h-4 text-xs whitespace-nowrap text-muted-foreground" aria-hidden="true" data-testid="ruler">
          {rulerMarks(length).map((m, i, all) => (
            <span
              key={i}
              className={cn('absolute top-0 -translate-x-1/2', i === 0 && 'translate-x-0', i === all.length - 1 && '-translate-x-full')}
              data-end={i === all.length - 1 || undefined}
              style={{ left: pct(m.at) }}>{m.label}</span>
          ))}
        </div>
      </div>
    </section>
  )
}
