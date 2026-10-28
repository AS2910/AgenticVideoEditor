import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  createProject, exportProject, artifactUrl,
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
  it('createProject uploads the file as multipart to /api/videos', async () => {
    const f = mockFetch(200, { project_id: 'p1', transcript: [] })
    vi.stubGlobal('fetch', f)
    const file = new File(['bytes'], 'ad.mp4', { type: 'video/mp4' })

    const project = await createProject(file, true)
    expect(project.project_id).toBe('p1')

    const [url, opts] = f.mock.calls[0]
    expect(url).toBe('/api/videos')
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
    expect((opts.body as FormData).get('file')).toBe(file)
    // The browser must set the multipart boundary itself: no Content-Type.
    // (Phase 9c adds the header that marks a write as Voltage's own; 2026-10-25 the tab it came from.)
    expect(opts.headers).toEqual({ 'X-Requested-With': 'voltage', 'X-Voltage-Tab': expect.any(String) })
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

  it('artifactUrl addresses stored media under the video', () => {
    expect(artifactUrl('p1', 'abc')).toBe('/api/videos/p1/artifacts/abc')
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

  it('exportProject posts to the export route', async () => {
    const f = mockFetch(200, { segments: [], render: null })
    vi.stubGlobal('fetch', f)
    await exportProject('p1')
    expect(f.mock.calls[0][0]).toBe('/api/videos/p1/export')
  })

  it('exportProject follows a render job and asks again for the render (run 4, item 3d)', async () => {
    vi.useFakeTimers()
    const job = { job_id: 'J4', status: 'running', error_text: null }
    let posts = 0
    let polls = 0
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) } as Response)
    const f = vi.fn(async (url: string) => {
      if (url.endsWith('/export')) { posts += 1; return reply(posts === 1 ? { render_job: job, request_id: 3 } : { segments: [], render: { sha256: 'r' }, version: 1, request_id: 3 }) }
      polls += 1
      return reply({ jobs: [{ ...job, status: polls < 2 ? 'running' : 'done' }], turn: null })
    })
    vi.stubGlobal('fetch', f)
    const seen: string[] = []
    const done = exportProject('p1', false, 3, 'preview', (j) => seen.push(j.job_id))
    await vi.runAllTimersAsync()
    const manifest = await done
    vi.useRealTimers()
    expect(manifest.version).toBe(1)
    expect(seen).toEqual(['J4'])
    expect(f.mock.calls.map(([u]) => u)).toEqual(['/api/videos/p1/export', '/api/videos/p1/jobs', '/api/videos/p1/jobs', '/api/videos/p1/export'])
  })

  it('exportProject throws the failed job\'s reason', async () => {
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) } as Response)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.endsWith('/export')
      ? reply({ render_job: { job_id: 'J5', status: 'queued' }, request_id: null })
      : reply({ jobs: [{ job_id: 'J5', status: 'failed', error_text: 'The render failed: no room' }], turn: null }))))
    await expect(exportProject('p1')).rejects.toMatchObject({ message: 'The render failed: no room' })
  })

  it('throws ApiError with status and the detail on non-2xx', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { detail: 'continuity check failed' }))
    await expect(exportProject('p1')).rejects.toMatchObject({ status: 422, message: 'continuity check failed' })
    await expect(exportProject('p1')).rejects.toBeInstanceOf(ApiError)
  })
})
