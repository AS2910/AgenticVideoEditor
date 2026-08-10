import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const PROJECT = {
  project_id: 'p1',
  transcript: [
    { text: 'Get', start: 0.0, end: 0.4 },
    { text: '20%', start: 0.4, end: 0.9 },
    { text: 'off', start: 0.9, end: 1.3 },
  ],
}

const PASSING_CONTINUITY = {
  voice_match: 0.95, prosody: 0.92, audio_integration: 0.97, lip_sync: 0.94,
  passed: true, warnings: [] as string[],
}

const CANDIDATE = {
  plan: { selection: { start: 0.4, end: 0.9 }, new_text: '30% off', voice_profile_id: 'speaker-1' },
  audio_ref: 'audio://x',
  frames_ref: 'frames://x',
  continuity: PASSING_CONTINUITY,
}

const SEGMENTS = [
  { start: 0, end: 0.4, kind: 'original', ref: 'sample-ad.mp4' },
  { start: 0.4, end: 0.9, kind: 'edited', ref: 'frames://x' },
  { start: 0.9, end: 2.3, kind: 'original', ref: 'sample-ad.mp4' },
]

const ok = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response

/** Routes by URL. `approveStatus` lets a test force the 422 branch. */
function routeFetch(approveStatus = 200) {
  return vi.fn(async (url: string) => {
    if (url.endsWith('/edits/preview')) return ok(CANDIDATE)
    if (url.endsWith('/edits')) {
      if (approveStatus !== 200) {
        return {
          ok: false,
          status: approveStatus,
          json: async () => ({ detail: 'continuity check failed' }),
          text: async () => 'continuity check failed',
        } as Response
      }
      return ok({ edit_id: 'e1', continuity: PASSING_CONTINUITY })
    }
    if (url.endsWith('/export')) return ok({ segments: SEGMENTS })
    if (url.endsWith('/projects')) return ok(PROJECT)
    throw new Error(`unexpected url ${url}`)
  })
}

/** consent -> load -> editor, leaving the app on the editor screen. */
async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: /continue/i }))
  await user.click(screen.getByRole('button', { name: /load sample ad/i }))
  await waitFor(() => expect(screen.getByText('20%')).toBeInTheDocument())
}

beforeEach(() => { vi.restoreAllMocks() })

describe('App full journey', () => {
  it('runs consent → load → select → preview → approve → export', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)

    await reachEditor(user)

    // Select a word, then prompt
    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())
    expect(screen.getByText(/continuity checked/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() => expect(screen.queryByText(/continuity checked/i)).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(screen.getAllByTestId('segment')).toHaveLength(3))
  })

  it('gates the editor behind consent', () => {
    vi.stubGlobal('fetch', routeFetch())
    render(<App />)
    expect(screen.getByText(/right to edit and clone the speaker/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load sample ad/i })).not.toBeInTheDocument()
  })

  it('cannot preview until a selection exists', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.type(screen.getByRole('textbox'), 'change the offer')
    expect(screen.getByRole('button', { name: /preview/i })).toBeDisabled()
  })

  it('surfaces a continuity failure when approve is rejected with 422', async () => {
    vi.stubGlobal('fetch', routeFetch(422))
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('20%'))
    await user.type(screen.getByRole('textbox'), 'change "20% off" to "30% off"')
    await user.click(screen.getByRole('button', { name: /preview/i }))
    await waitFor(() => expect(screen.getByText('30% off')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /approve/i }))

    // Honest failure: message shown and the candidate is NOT silently dropped.
    await waitFor(() =>
      expect(screen.getByText(/continuity check failed/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('30% off')).toBeInTheDocument()
  })

  it('reflects the backend snapped selection on the timeline', async () => {
    vi.stubGlobal('fetch', routeFetch())
    const user = userEvent.setup()
    render(<App />)
    await reachEditor(user)

    await user.click(screen.getByText('Get')) // 0.0–0.4
    await user.type(screen.getByRole('textbox'), 'change it')
    await user.click(screen.getByRole('button', { name: /preview/i }))

    // Backend returns 0.4–0.9; the timeline region must follow it.
    await waitFor(() => {
      const region = screen.getByTestId('selection-region')
      expect(region.style.left).toMatch(/^17\.39/) // 0.4 / 2.3
    })
  })
})
