import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createProject, previewEdit, approveEdit, exportProject, ApiError } from './api'

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
  it('createProject posts filename+duration to /api/projects', async () => {
    const f = mockFetch(200, { project_id: 'p1', transcript: [] })
    vi.stubGlobal('fetch', f)
    const project = await createProject('ad.mp4', 30)
    expect(project.project_id).toBe('p1')
    const [url, opts] = f.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ filename: 'ad.mp4', duration: 30 })
  })

  it('previewEdit posts the edit request to the preview route', async () => {
    const f = mockFetch(200, { plan: {}, audio_ref: 'a', frames_ref: 'f', continuity: {} })
    vi.stubGlobal('fetch', f)
    await previewEdit('p1', { prompt: 'x', start: 0.5, end: 1, voice_profile_id: 'speaker-1' })
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits/preview')
  })

  it('approveEdit hits the edits route', async () => {
    const f = mockFetch(200, { edit_id: 'e1', continuity: {} })
    vi.stubGlobal('fetch', f)
    const res = await approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'speaker-1' })
    expect(res.edit_id).toBe('e1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/edits')
  })

  it('exportProject posts to the export route', async () => {
    const f = mockFetch(200, { segments: [] })
    vi.stubGlobal('fetch', f)
    await exportProject('p1')
    expect(f.mock.calls[0][0]).toBe('/api/projects/p1/export')
  })

  it('throws ApiError with status on non-2xx', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { detail: 'continuity check failed' }))
    await expect(
      approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'unknown' }),
    ).rejects.toMatchObject({ status: 422 })
    expect(
      approveEdit('p1', { prompt: 'x', start: 0, end: 1, voice_profile_id: 'unknown' }),
    ).rejects.toBeInstanceOf(ApiError)
  })
})
