import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import styles from './Player.module.css'

interface PlayerProps {
  src: string
  duration: number
  currentTime: number
  onSeek: (t: number) => void
  /** Called as the video plays, with its own clock. */
  onTimeUpdate?: (t: number) => void
  /** A seek asked for from outside (e.g. the transcript). `id` makes asking
   *  for the same time twice still move the video. */
  seekRequest?: { time: number; id: number } | null
  /** Moments to mark on the progress bar: where the changes are. */
  marks?: number[]
  /** Shown at the end of the transport row (e.g. the Edited / Original switch). */
  children?: ReactNode
}

/** m:ss.cc — hundredths, because edits land between words. */
const timecode = (t: number) => {
  const safe = Math.max(0, t)
  const m = Math.floor(safe / 60)
  const s = (safe - m * 60).toFixed(2).padStart(5, '0')
  return `${m}:${s}`
}

export function Player({
  src, duration, currentTime, onSeek, onTimeUpdate, seekRequest, marks = [], children,
}: PlayerProps) {
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

  useEffect(() => {
    if (seekRequest && videoRef.current) videoRef.current.currentTime = seekRequest.time
  }, [seekRequest])

  const toggle = () => {
    const video = videoRef.current
    if (video) {
      if (playing) video.pause()
      else void video.play().catch(() => {})
    }
    setPlaying((p) => !p)
  }

  const seek = (t: number) => {
    if (videoRef.current) videoRef.current.currentTime = t
    onSeek(t)
  }

  const played = length > 0 ? Math.min(100, (currentTime / length) * 100) : 0
  return (
    <div className={styles.player}>
      <div className={styles.stage}>
        <video
          ref={videoRef}
          className={styles.video}
          src={src}
          playsInline
          onLoadedMetadata={(e) => {
            const d = e.currentTarget.duration
            if (Number.isFinite(d) && d > 0) setLength(d)
          }}
          onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
          onEnded={() => setPlaying(false)}
        />
      </div>
      <div className={styles.controls}>
        <button className={styles.play} onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? (
            <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1h3v10H1zM6 1h3v10H6z" fill="currentColor" /></svg>
          ) : (
            <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
          )}
        </button>
        <span className={styles.timecode} data-testid="timecode">
          {timecode(currentTime)} <span className={styles.of}>/ {timecode(length)}</span>
        </span>
        <div className={styles.bar}>
          <div className={styles.played} style={{ width: `${played}%` }} />
          {marks.filter((t) => t >= 0 && t <= length).map((t, i) => (
            <span key={i} className={styles.mark} data-testid="mark" style={{ left: `${(t / length) * 100}%` }} />
          ))}
          <input
            className={styles.scrubber}
            type="range"
            min={0}
            max={length}
            step={0.01}
            value={Math.min(currentTime, length)}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
          />
        </div>
        {children}
      </div>
    </div>
  )
}
