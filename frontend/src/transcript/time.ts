/** m:ss.cc, as the transport shows it. */
export const timecode = (t: number) => {
  const safe = Math.max(0, t)
  const m = Math.floor(safe / 60)
  const s = (safe - m * 60).toFixed(2).padStart(5, '0')
  return `${m}:${s}`
}

/** Reads "4.96", "0:04.96" or "1:02" as seconds; null when it is not a time. */
export const parseTime = (text: string): number | null => {
  const t = text.trim()
  const clock = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(t)
  if (clock) return parseInt(clock[1], 10) * 60 + parseFloat(clock[2])
  const n = parseFloat(t)
  return Number.isFinite(n) && /^\d+(\.\d+)?$/.test(t) ? n : null
}
