import { describe, expect, it } from 'vitest'
import { lipsNote } from './lips'

describe('lipsNote (Run 5, item 10)', () => {
  it('names the speaker, capitalised at the start of the sentence', () => {
    expect(lipsNote('on_camera', 'the Customer')).toBe("The Customer is on screen saying this line, so the lips won't match yet.")
    expect(lipsNote('unsure', null)).toBe("The speaker may be on screen here. If so, the lips won't match yet.")
  })
  it('says nothing off camera or before the look has finished', () => {
    expect(lipsNote('off_camera', 'Ana')).toBeNull()
    expect(lipsNote(null, 'Ana')).toBeNull()
    expect(lipsNote(undefined, 'Ana')).toBeNull()
  })
})
