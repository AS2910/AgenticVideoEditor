import type { OnCamera } from '../types'

/** Run 5, item 10: the honest note on a changed line whose speaker is seen
 *  saying it. No lip-sync yet, so new words there will not match the mouth.
 *  An off-camera line (or one not looked at yet) gets no note: it is edited freely.
 *  Same voice as the moved-line note ("Lines move, the picture doesn't..."). */
export function lipsNote(state: OnCamera | null | undefined, who: string | null | undefined): string | null {
  const name = who ?? 'the speaker'
  const Name = name.replace(/^./, (c) => c.toUpperCase())
  if (state === 'on_camera') return `${Name} is on screen saying this line, so the lips won't match yet.`
  if (state === 'unsure') return `${Name} may be on screen here. If so, the lips won't match yet.`
  return null
}
