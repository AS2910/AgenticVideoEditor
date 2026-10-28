import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BusyHint } from './BusyHint'
import { busyWith, editingWho, stripState } from '../jobs/model'
import type { ActivityJob, VideoLock } from '../types'

/** One edit at a time per video (2026-10-25): the strip names the action, a locked control says
 *  what the video is busy with, another tab or member reads "<name> is editing". */

const lock = (over: Partial<VideoLock> = {}): VideoLock => ({
  video_id: 'p1', holder: 'J4', action: "Adding 'Fresh every morning'", started_by: 'local', started_by_name: 'You', tab: 'me',
  started_at: '2026-10-25T10:00:00Z', stoppable: true, waiting: false, lease_expires_at: '2026-10-25T10:01:30Z', ...over,
})
const job = (over: Partial<ActivityJob> = {}): ActivityJob => ({
  job_id: 'J4', video_id: 'p1', turn_id: null, kind: 'render_preview', status: 'running', step_label: 'Rendering preview v3', progress: 0.4,
  line_ids: ['e1'], created_at: '2026-10-25T10:00:00Z', started_at: '2026-10-25T10:00:00Z', finished_at: null, eta_s: 8,
  error_code: null, error_text: null, cost_usd: null, detail: { mode: 'final', added: true, version: 3 }, ...over,
})
const facts = { playing: null, stale: false }

describe('the status strip names the action that holds the video', () => {
  it('an Add, with its time', () => {
    expect(stripState({ ...facts, jobs: [job()], turn: null, lock: lock() }).text).toBe("Adding 'Fresh every morning'… · about 8 s")
  })
  it('an undo', () => {
    expect(stripState({ ...facts, jobs: [], turn: null, lock: lock({ holder: 'req-1', action: 'Undoing', stoppable: false }) }).text).toBe('Undoing…')
  })
  it('a turn that is planning, then voicing line 3 of 5', () => {
    const turn = { turn_id: 'j1', status: 'running' as const, step: 'Thinking', started_at: '', finished_at: null }
    const held = lock({ holder: 'turn:j1', action: 'Voltage is planning' })
    expect(stripState({ ...facts, jobs: [], turn, lock: held }).text).toBe('Voltage is planning…')
    const voices = [1, 2, 3, 4, 5].map((k) => job({ job_id: `V${k}`, kind: 'voice_line', turn_id: 'j1', status: k < 3 ? 'done' : k === 3 ? 'running' : 'queued', step_label: 'Voicing', line_ids: [`i${k}`], eta_s: null, detail: {} }))
    expect(stripState({ ...facts, jobs: voices, turn, lock: held }).text).toBe('Voicing line 3 of 5')
  })
  it('a go Voltage waits for', () => {
    expect(stripState({ ...facts, jobs: [], turn: null, lock: lock({ holder: 'gate:j1', waiting: true, action: 'Waiting for your go' }) }).text).toBe('Waiting for your go')
  })
  it("another member's work reads as theirs", () => {
    const theirs = lock({ started_by: 'google:ann', started_by_name: 'Ann', tab: 'their-tab' })
    expect(stripState({ ...facts, jobs: [job()], turn: null, lock: theirs, othersLock: true }).text).toBe("Ann is editing · Adding 'Fresh every morning'… · about 8 s")
    expect(editingWho(lock({ tab: 'other' }))).toBe('Another tab is editing')
  })
  it('nothing held: as before', () => {
    expect(stripState({ ...facts, jobs: [], turn: null, lock: null }).text).toBe('Up to date')
  })
})

describe('a locked control says what the video is busy with', () => {
  it('in words', () => {
    expect(busyWith(lock())).toBe("Busy with adding 'Fresh every morning'")
    expect(busyWith(lock({ holder: 'turn:j1', action: 'Voltage is planning' }))).toBe("Busy with Voltage's turn")
    expect(busyWith(lock({ started_by_name: 'Ann' }), true)).toBe("Ann is editing: Busy with adding 'Fresh every morning'")
  })

  it('the card offers Queue this change and Stop, and closes on Escape', async () => {
    const onQueue = vi.fn()
    const onStop = vi.fn()
    const onClose = vi.fn()
    const { rerender } = render(<BusyHint ask={{ text: busyWith(lock()), change: 'Add line 2' }} onQueue={onQueue} onStop={onStop} onClose={onClose} />)
    expect(screen.getByTestId('busy-text')).toHaveTextContent("Busy with adding 'Fresh every morning'. Add line 2 can wait in Up next.")
    await userEvent.click(screen.getByTestId('queue-this'))
    expect(onQueue).toHaveBeenCalledOnce()
    rerender(<BusyHint ask={{ text: busyWith(lock()) }} onStop={onStop} onClose={onClose} />)
    await userEvent.click(screen.getByTestId('busy-stop'))
    expect(onStop).toHaveBeenCalledOnce()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
    rerender(<BusyHint ask={{ text: "Ann is editing: Busy with adding 'x'" }} onClose={onClose} />)
    expect(screen.queryByTestId('queue-this')).toBeNull()
    expect(screen.queryByTestId('busy-stop')).toBeNull()
  })
})
