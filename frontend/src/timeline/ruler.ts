import { clock } from '../transcript/format'

/** The ruler: a label every `step` seconds, chosen so there are about five, and the end. */
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
export function rulerMarks(length: number): { at: number; label: string }[] {
  if (!(length > 0)) return []
  const step = RULER_STEPS.find((s) => length / s <= 5.5) ?? 600
  const marks: { at: number; label: string }[] = []
  // The last regular label gives way to the end label when they would touch.
  for (let t = 0; t < length - Math.max(step * 0.2, length * 0.06); t += step) {
    marks.push({ at: t, label: step < 1 ? `${clock(t)}.${Math.round((t % 1) * 10)}` : clock(t) })
  }
  const tenth = Math.round((length % 1) * 10)
  marks.push({ at: length, label: length < 10 && tenth > 0 && tenth < 10 ? `${clock(length)}.${tenth}` : clock(Math.round(length)) })
  return marks
}
