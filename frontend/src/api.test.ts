import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  createProject, previewEdit, approveEdit, exportProject, artifactUrl,
  pollJob, PollCancelled, ApiError,
} from './api'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response)
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

describe('api client', () => {
  it('createProject uploads the file as multipart to /api/projects', async () => {
    const f = mockFetch(200, { project_id: 'p1', transcript: [] })
    vi.stubGlobal('fetch', f)
    const file = new File(['bytes'], 'ad.mp4', { type: 'video/mp4' })

    const project = await createProject(file, true)
    expect(project.project_id).toBe('p1')

    const [url, opts] = f.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
    expect((opts.body as FormData).get('file')).toBe(file)
    // The browser must set the multipart boundary itself.
    expect(opts.headers).toBeUndefined()
  })

  it('sends the uploader consent confirmation with the upload', async () => {
    const f = mockFetch(200, { project_id: 'p1', transcript: [] })
    vi.stubGlobal('fetch', f)
    const file = new File(['bytes'], 'ad.mp4', { type: 'video/mp4' })

    await createProject(file, true)
    expect((f.mock.calls[0][1].body as FormData).get('consent')).toBe('true')

    await createProject(file, false)
    expect((f.mock.calls[1][1].body as FormData).get('consent')).toBe('false')
  })

  it('surfaces the backend rejection reason on a failed upload', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { detail: 'That file has no video track.' }))
    await expect(
      createProject(new File([''], 'notes.txt'), true),
    ).rejects.toMatchObject({ status: 422, message: 'That file has no video track.' })
  })

  it('artifactUrl addresses stored media under the project', () => {
    expect(artifactUrl('p1', 'abc')).toBe('/api/projects/p1/artifacts/abc')
  })

  describe('pollJob', () => {
    const job = (over: Record<string, unknown> = {}) => ({
      job_id: 'j1', kind: 'preview', project_id: 'p1',
      status: 'running', progress: 0.5, step: 'Working',
      attempts: 1, result: null, error: null, ...over,
    })

    function queuedFetch(bodies: unknown[]) {
      let i = 0
      return vi.fn(async (_url: string, _init?: RequestInit) => {
        const body = bodies[Math.min(i++, bodies.length - 1)]
        return { ok: true, status: 200, json: async () => body, text: async () => '' } as Response
      })
    }

    it('keeps polling until the job reaches a terminal state', async () => {
      const f = queuedFetch([job(), job(), job({ status: 'succeeded', progress: 1 })])
      vi.stubGlobal('fetch', f)

      const finished = await pollJob('j1', { intervalMs: 1 })
      expect(finished.status).toBe('succeeded')
      expect(f).toHaveBeenCalledTimes(3)
      expect(f.mock.calls[0][0]).toBe('/api/jobs/j1')
    })

    it('reports every tick so the UI can show progress', async () => {
      vi.stubGlobal('fetch', queuedFetch([
        job({ progress: 0.2, step: 'A' }),
        job({ status: 'succeeded', progress: 1, step: 'Ready' }),
      ]))
      const seen: string[] = []

      await pollJob('j1', { intervalMs: 1, onUpdate: (j) => seen.push(j.step) })
      expect(seen).toEqual(['A', 'Ready'])
    })

    it('returns a failed job rather than throwing', async () => {
      vi.stubGlobal('fetch', queuedFetch([job({ status: 'failed', error: 'nope' })]))
      const finished = await pollJob('j1', { intervalMs: 1 })
      expect(finished.status).toBe('failed')
      expect(finished.error).toBe('nope')
    })

    it('stops when superseded, so a stale poll cannot overwrite a newer one', async () => {
      const f = queuedFetch([job()])
      vi.stubGlobal('fetch', f)

      await expect(
        pollJob('j1', { intervalMs: 1, shouldStop: () => true }),
      ).rejects.toBeInstanceOf(PollCancelled)
      expect(f).not.toHaveBeenCalled()
    })

    it('gives up once the deadline passes', async () => {
      vi.stubGlobal('fetch', queuedFetch([job()]))
      await expect(
        pollJob('j1', { intervalMs: 1, timeoutMs: -1 }),
      ).rejects.toThrow(/timed out/i)
    })
  })

  it('previewEdit posts the edit request to the preview route', async () => {
    const f = mockFetch(200, { candidate_id: 'c1', plan: {}, audio: {}, frames: {}, continuity: {} })
    vi.stubGlobal('fetch', f)
    await previewEdit('p1', { prompt: 'x', start: 0.5, end: 1, voice_profile_id: 'speaker-1' })
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits/preview')
  })

  it('approveEdit posts just the candidate id to the edits route', async () => {
    const f = mockFetch(200, { edit_id: 'e1', candidate_id: 'c1', continuity: {} })
    vi.stubGlobal('fetch', f)
    const res = await approveEdit('p1', 'c1')
    expect(res.edit_id).toBe('e1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits')
    // The previewed candidate is named, not re-described — the server must not
    // regenerate media on approval.
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ candidate_id: 'c1' })
  })

  it('exportProject posts to the export route', async () => {
    const f = mockFetch(200, { segments: [], render: null })
    vi.stubGlobal('fetch', f)
    await exportProject('p1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/export')
  })

  it('throws ApiError with status on non-2xx', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { detail: 'continuity check failed' }))
    await expect(approveEdit('p1', 'c1')).rejects.toMatchObject({ status: 422 })
    await expect(approveEdit('p1', 'c1')).rejects.toBeInstanceOf(ApiError)
  })

  it('approveEdit sends override only when asked', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      ({ ok: true, status: 200, json: async () => ({}) }) as Response)
    vi.stubGlobal('fetch', fetchMock)
    await approveEdit('p1', 'c1', true)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      candidate_id: 'c1', override: true,
    })
  })
})
