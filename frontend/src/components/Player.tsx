import { useRef, useState } from 'react'
import styles from './Player.module.css'

interface PlayerProps {
  src: string
  duration: number
  currentTime: number
  onSeek: (t: number) => void
}

export function Player({ src, duration, currentTime, onSeek }: PlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)

  const toggle = () => {
    const video = videoRef.current
    if (video) {
      if (playing) video.pause()
      else void video.play().catch(() => {})
    }
    setPlaying((p) => !p)
  }

  return (
    <div className={styles.player}>
      <div className={styles.stage}>
        <video ref={videoRef} className={styles.video} src={src} muted playsInline />
      </div>
      <div className={styles.controls}>
        <button className={styles.play} onClick={toggle}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <input
          className={styles.scrubber}
          type="range"
          min={0}
          max={duration}
          step={0.01}
          value={currentTime}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Seek"
        />
      </div>
    </div>
  )
}
