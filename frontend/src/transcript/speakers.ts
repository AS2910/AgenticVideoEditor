import type { Speaker } from '../types'

/** Which of the speaker colours a label gets: by its place in the cast. */
export const speakerSlot = (speakers: Speaker[], label?: string | null): string => {
  const i = speakers.findIndex((s) => s.label === label)
  return i < 0 ? 'x' : 'abcd'[i % 4]
}
