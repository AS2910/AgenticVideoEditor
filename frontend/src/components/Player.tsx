import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Word } from '../types'
import { rulerMarks } from '../timeline/ruler'
import styles from './Player.module.css'

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
    <section className={styles.player} aria-label="Monitor">
      <div className={styles.stage}>
        <video
          ref={videoRef}
          className={styles.video}
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
        {caption && (playing || currentTime > 0) && <div className={styles.caption} data-testid="caption" aria-hidden="true">{caption}</div>}
      </div>
      <div className={styles.transport}>
        <div className={styles.controls}>
          <button className={styles.play} onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? (
              <svg width="12" height="14" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1h3v10H1zM6 1h3v10H6z" fill="currentColor" /></svg>
            ) : (
              <svg width="12" height="14" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
            )}
          </button>
          <span className={styles.timecode} data-testid="timecode">
            {timecode(currentTime)} <span className={styles.of}>/ {timecode(length)}</span>
          </span>
          {children}
        </div>
        {/* The timeline: the lines as blocks, the changes lit, the words as
            ticks, the playhead, and the real range input laid invisibly over
            it all so it stays a slider. */}
        <div className={styles.track} ref={barRef}>
          {blocks.filter((b) => b.end > 0 && b.start < length).map((b, i) => (
            <span
              key={i}
              className={styles.block}
              data-tone={b.tone}
              data-testid="block"
              style={{ left: pct(b.start), width: `${Math.max(0.4, ((Math.min(b.end, length) - Math.max(0, b.start)) / Math.max(length, 0.001)) * 100)}%` }}
            />
          ))}
          {words.filter((w) => w.start >= 0 && w.start <= length).map((w, i) => (
            <span key={i} className={styles.tick} data-testid="tick" style={{ left: pct(w.start) }} />
          ))}
          {placing && length > 0 && (
            <div
              className={styles.placing}
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
          <span className={styles.head} data-testid="head" style={{ left: `${head}%` }} />
          <input
            className={styles.scrubber}
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
        <div className={styles.ruler} aria-hidden="true" data-testid="ruler">
          {rulerMarks(length).map((m, i, all) => (
            <span key={i} className={styles.rulerMark} data-end={i === all.length - 1 || undefined} style={{ left: pct(m.at) }}>{m.label}</span>
          ))}
        </div>
      </div>
    </section>
  )
}
