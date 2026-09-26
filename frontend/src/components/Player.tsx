import { useEffect, useRef, useState } from 'react'
import styles from './Player.module.css'

interface PlayerProps {
  src: string
  duration: number
  currentTime: number
  onSeek: (t: number) => void
  /** Called as the video plays, with its own clock. */
  onTimeUpdate?: (t: number) => void
}

export function Player({ src, duration, currentTime, onSeek, onTimeUpdate }: PlayerProps) {
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
        <button className={styles.play} onClick={toggle}>
          {playing ? 'Pause' : 'Play'}
        </button>
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
    </div>
  )
}
