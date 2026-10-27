import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BatchExport } from './BatchExport'
import { resetFlags } from '../flags/useFlags'
import { ExportPresets } from './ExportPresets'
import { SharePage } from './SharePage'
import { fileSize, presetFacts, shareToken } from '../lib/exports'
import type { ExportPreset } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const preset = (preset_id: number, name: string, platform: ExportPreset['platform'], extra: Partial<ExportPreset> = {}): ExportPreset => ({
  preset_id, project_id: 'f1', name, platform, codec: 'h264', loudness: -14, captions: false, pattern: '{project}_{video}_{lang}_{preset}_v{version}',
  position: preset_id, created_by: 'local', created_at: '2026-10-20T10:00:00.000Z', updated_at: '2026-10-20T10:00:00.000Z', ...extra })
const PRESETS = [preset(1, 'YouTube 16:9', 'youtube'), preset(2, 'Reels 9:16', 'reels')]
const VIDEOS = [
  { video_id: 'p1', filename: 'bhaji-cam.mp4', duration: 30, stage: 'approved', stage_label: 'Approved', approved: true },
  { video_id: 'p2', filename: 'offer.mp4', duration: 20, stage: 'draft', stage_label: 'Draft', approved: false },
]
const WARN = { kind: 'fact', message: 'The videos give different percentages: 20% in bhaji-cam.mp4; 30% in offer.mp4.', places: [], fingerprint: 'fp1' }
const file = (index: number, video_id: string, p: ExportPreset, state: string, extra = {}) => ({
  index, video_id, filename: `${video_id}.mp4`, stage: 'approved', approved: video_id === 'p1', preset: p, attempts: 1, job_id: `J${index}`, state,
  label: { ready: 'Ready', failed: 'Failed', queued: 'Queued', rendering: 'Rendering' }[state], why: null,
  file: state === 'ready' ? { name: `Diwali_${video_id}_en_${p.name}_v1.mp4`, size: 2_400_000, version: 1, duration: 30, report: { framing: 'Fills the frame.', width: 1920, height: 1080, loudness_lufs: -14, loudness_target: -14, captions: 0 } } : null,
  ...extra })

describe('B3: export videos', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags() })

  it('without stages (phase C off) picks every video and flags none as not approved', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch'] })
      if (url.endsWith('/exports/preflight')) return ok({ videos: VIDEOS, warnings: [] })
      if (url.endsWith('/projects/f1/exports')) return ok({ exports: [] })
      throw new Error(`unexpected ${url}`)
    }))
    render(<BatchExport projectId="f1" presets={PRESETS} />)
    const rows = await screen.findAllByTestId('export-video')
    await waitFor(() => expect(within(rows[1]).getByRole('checkbox')).toBeChecked())
    expect(within(rows[0]).getByRole('checkbox')).toBeChecked()
    expect(screen.queryByText('Not approved')).not.toBeInTheDocument()
    expect(screen.queryByTestId('export-warnings')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export 2 files' })).toBeEnabled()
  })

  it('picks Approved videos by default, flags others, warns before exporting, and starts one file per video and preset', async () => {
    const calls: string[] = []
    let started: object | null = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch', 'projects.review'] })
      const method = init?.method ?? 'GET'
      if (method !== 'GET') calls.push(`${method} ${url} ${init?.body ?? ''}`)
      if (url.endsWith('/exports/preflight')) return ok({ videos: VIDEOS, warnings: [WARN] })
      if (url.endsWith('/projects/f1/exports') && method === 'GET') return ok({ exports: started ? [started] : [] })
      if (url.endsWith('/projects/f1/exports') && method === 'POST') {
        started = { export_id: 'J9', project_id: 'f1', created_at: '', finished_at: null, phase: 'running', status: 'running', step: '0 of 4 files ready', progress: 0, warnings: [], files: [file(0, 'p1', PRESETS[0], 'queued')], counts: { total: 4, ready: 0, failed: 0 }, share: null }
        return ok(started, 201)
      }
      throw new Error(`unexpected ${method} ${url}`)
    }))
    render(<BatchExport projectId="f1" presets={PRESETS} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the exports…')
    const rows = await screen.findAllByTestId('export-video')
    expect(await within(rows[1]).findByText('Not approved')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('checkbox')).toBeChecked()
    expect(within(rows[1]).getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByTestId('export-warnings')).toHaveTextContent(WARN.message)
    expect(screen.getByRole('button', { name: 'YouTube 16:9' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Export 1 file' })).toBeEnabled()
    await userEvent.click(within(rows[1]).getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Reels 9:16' }))
    expect(screen.getByTestId('export-warnings')).toHaveTextContent('offer.mp4 is not approved yet.')
    await userEvent.click(screen.getByRole('button', { name: 'Export 4 files' }))
    expect(calls).toEqual(['POST /api/projects/f1/exports {"video_ids":["p1","p2"],"preset_ids":[1,2]}'])
    expect(await screen.findByText('Exporting 4 files')).toBeInTheDocument()
  })

  it('shows each file, a failure with its reason, the zip and a share link', async () => {
    const run = { export_id: 'J9', project_id: 'f1', created_at: '', finished_at: '2026-10-21T10:00:00.000Z', phase: 'finished', status: 'done', step: '1 of 2 files ready, 1 failed', progress: 1, warnings: [],
      files: [file(0, 'p1', PRESETS[0], 'ready'), file(1, 'p2', PRESETS[0], 'failed', { why: 'The render failed twice. the encoder crashed.', attempts: 2 })],
      counts: { total: 2, ready: 1, failed: 1 }, share: null as null | object }
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch', 'projects.review'] })
      const method = init?.method ?? 'GET'
      if (url.endsWith('/exports/preflight')) return ok({ videos: VIDEOS, warnings: [] })
      if (url.endsWith('/projects/f1/exports')) return ok({ exports: [run] })
      if (url.endsWith('/exports/J9/share') && method === 'POST') {
        run.share = { share_id: 'sh1', scope: 'export', target: 'J9', role: 'viewer', name: null, created_at: '', expires_at: '2026-11-20T10:00:00.000Z', revoked_at: null, state: 'live', url: 'http://localhost:5173/#s/sh1.sig' }
        return ok(run.share, 201)
      }
      if (url.endsWith('/onboarding')) return ok({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
      throw new Error(`unexpected ${method} ${url}`)
    }))
    render(<BatchExport projectId="f1" presets={PRESETS} />)
    expect(await screen.findByText('Export finished')).toBeInTheDocument()
    const [ready, failed] = screen.getAllByTestId('export-file')
    expect(ready).toHaveAttribute('data-state', 'ready')
    expect(within(ready).getByRole('link', { name: /Download Diwali_p1/ })).toHaveAttribute('href', '/api/projects/f1/exports/J9/files/0?download=true')
    expect(within(failed).getByText('The render failed twice. the encoder crashed.')).toBeInTheDocument()
    expect(await within(failed).findByText('Not approved')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download all (.zip)' })).toHaveAttribute('href', '/api/projects/f1/exports/J9/zip')
    await userEvent.click(screen.getByRole('button', { name: 'Share link' }))
    expect(await screen.findByRole('textbox', { name: 'Share link' })).toHaveValue('http://localhost:5173/#s/sh1.sig')
    expect(screen.getByTestId('export-share')).toHaveTextContent('no account needed')
    await userEvent.click(screen.getByRole('button', { name: 'Export again' }))
    expect(await screen.findByTestId('export-pick')).toBeInTheDocument()
  })

  it('says when there is nothing to export and when the read fails', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch', 'projects.review'] })
      if (fail) return ok({ detail: 'Server down.' }, 500)
      if (url.endsWith('/exports/preflight')) return ok({ videos: [], warnings: [] })
      return ok({ exports: [] })
    }))
    render(<BatchExport projectId="f1" presets={PRESETS} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server down.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('export-empty')).toBeInTheDocument()
  })
})

const PAGE = { presets: PRESETS, platforms: [{ id: 'youtube', label: 'YouTube 16:9', width: 1920, height: 1080 }, { id: 'reels', label: 'Reels 9:16', width: 1080, height: 1920 }, { id: 'feed', label: 'Feed 1:1', width: 1080, height: 1080 }],
  codecs: [{ id: 'h264', label: 'H.264', available: true }, { id: 'hevc', label: 'HEVC (H.265)', available: false }],
  loudness: [{ lufs: -14, label: 'Web · -14 LUFS' }, { lufs: -16, label: 'General · -16 LUFS' }, { lufs: -24, label: 'Broadcast · -24 LUFS' }],
  tokens: ['project', 'video', 'lang', 'preset', 'version'], default_pattern: '{project}_{video}_{lang}_{preset}_v{version}', captions: true }

describe('B3: presets', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists presets with their facts, adds one and removes one', async () => {
    const calls: string[] = []
    const onChanged = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (method !== 'GET') calls.push(`${method} ${url} ${init?.body ?? ''}`)
      if (method === 'GET') return ok(PAGE)
      if (method === 'POST') return ok(preset(3, 'TV spot', 'youtube', { loudness: -24, captions: true }), 201)
      if (method === 'DELETE') return ({ ok: true, status: 204, json: async () => null, text: async () => '' }) as Response
      throw new Error(`unexpected ${method} ${url}`)
    }))
    render(<ExportPresets projectId="f1" onChanged={onChanged} />)
    const rows = await screen.findAllByTestId('preset')
    expect(rows[1]).toHaveTextContent('Reels 9:16 · H.264 · -14 LUFS · No captions')
    await userEvent.click(screen.getByRole('button', { name: '+ Add preset' }))
    const form = screen.getByTestId('preset-form')
    expect(within(form).getByRole('button', { name: 'HEVC (H.265)' })).toBeDisabled()
    await userEvent.type(within(form).getByLabelText('Name', { exact: true }), 'TV spot')
    await userEvent.click(within(form).getByRole('button', { name: 'Broadcast · -24 LUFS' }))
    await userEvent.click(within(form).getByRole('checkbox'))
    await userEvent.click(within(form).getByRole('button', { name: 'Save preset' }))
    await waitFor(() => expect(screen.getAllByTestId('preset')).toHaveLength(3))
    expect(JSON.parse(calls[0].split(' ').slice(2).join(' '))).toEqual({ name: 'TV spot', platform: 'youtube', codec: 'h264', loudness: -24, captions: true, pattern: PAGE.default_pattern })
    await userEvent.click(screen.getByRole('button', { name: 'Remove YouTube 16:9' }))
    await waitFor(() => expect(screen.getAllByTestId('preset')).toHaveLength(2))
    expect(onChanged).toHaveBeenLastCalledWith([PRESETS[1], expect.objectContaining({ name: 'TV spot' })])
  })

  it('shows the server saying no beside the form', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => (init?.method === 'PATCH' ? ok({ detail: 'Put {video} in the pattern, so every video gets its own file.' }, 422) : ok(PAGE))))
    render(<ExportPresets projectId="f1" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Reels 9:16' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save preset' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Put {video} in the pattern')
  })
})

describe('F6: the share page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('plays and downloads every file, with the zip', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ scope: 'export', role: 'viewer', name: null, expires_at: '2026-11-20T10:00:00.000Z', title: 'Diwali Sale', exported_at: '2026-10-21T10:00:00.000Z',
      files: [{ file_id: '0', name: 'a.mp4', kind: 'video', size: 2_400_000, duration: 30, label: 'Reels 9:16 · a.mp4' }, { file_id: '1', name: 'b.mp4', kind: 'video', size: 900, duration: null, label: null }] })))
    render(<SharePage token="sh1.sig" />)
    expect(await screen.findByRole('heading', { name: 'Diwali Sale' })).toBeInTheDocument()
    const files = screen.getAllByTestId('share-file')
    expect(files[0].querySelector('video')).toHaveAttribute('src', '/api/share/sh1.sig/files/0')
    expect(within(files[0]).getByRole('link', { name: 'Download a.mp4' })).toHaveAttribute('href', '/api/share/sh1.sig/files/0?download=true')
    expect(within(files[0]).getByText('2.4 MB · 0:30')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download all (.zip)' })).toHaveAttribute('href', '/api/share/sh1.sig/zip')
  })

  it('says plainly when a link has expired', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'This link has expired. Ask the person who shared it for a new one.' }, 410)))
    render(<SharePage token="sh1.sig" />)
    expect(await screen.findByTestId('share-refused')).toHaveTextContent('This link has expired. Ask the person who shared it for a new one.')
  })

  it('reads helpers right', () => {
    expect(shareToken('#s/sh12ab.Zz-_9')).toBe('sh12ab.Zz-_9')
    expect(shareToken('#p/f1')).toBeNull()
    expect(fileSize(900)).toBe('1 KB')
    expect(presetFacts(preset(1, 'x', 'feed', { captions: true, loudness: -24 }), null)).toBe('feed · h264 · -24 LUFS · Captions burned in')
  })
})
