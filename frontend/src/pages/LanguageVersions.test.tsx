import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LanguageChips, LanguageDialog, SyncChip } from './LanguageVersions'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const SET = {
  master_id: 'p1', master_filename: 'bhaji-cam.mp4', original: 'en', original_label: 'English', in_project: true, lines: 4,
  children: [{ video_id: 'p2', language: 'ta', label: 'Tamil', out_of_sync: false }],
  options: [{ code: 'hi', label: 'Hindi', made: false }, { code: 'hinglish', label: 'Hinglish', made: false }, { code: 'ta', label: 'Tamil', made: true }, { code: 'mr', label: 'Marathi', made: false }],
}
const gate = (n: number) => ({ videos: n, lines: 4 * n, est_usd: 0.12 * n, cap_usd: 0.5 * n, per_video_cap_usd: 0.5 })

describe('B2: language versions', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('picks languages and the voice handling, shows the numbers first, then makes them', async () => {
    const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return ok(SET)
      const body = JSON.parse(String(init?.body))
      posts.push(JSON.stringify(body))
      return ok({ gate: gate(body.languages.length), batch_id: body.dry_run ? null : 'J1', children: [] }, 201)
    }))
    const made = vi.fn()
    render(<LanguageDialog videoId="p1" filename="bhaji-cam.mp4" projectId="f1" onClose={() => {}} onMade={made} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the languages')
    expect(await screen.findByText(/this video is in English/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Tamil/ })).toBeDisabled()                // made already
    expect(screen.getByRole('button', { name: 'Make versions' })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /Hindi/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Marathi/ }))
    await userEvent.click(screen.getByRole('radio', { name: /A designed voice per language/ }))
    expect(await screen.findByText('2 versions · 8 lines · about $0.24')).toBeInTheDocument()
    expect(screen.getByText(/Spends at most \$1.00/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Make 2 versions' }))
    await waitFor(() => expect(made).toHaveBeenCalledWith('f1'))
    expect(posts.at(-1)).toBe(JSON.stringify({ languages: ['hi', 'mr'], voice: 'designed' }))
    expect(posts.some((p) => p.includes('"dry_run":true'))).toBe(true)
  })

  it('asks for a project first, and says why a read failed with Try again', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => (fail ? ok({ detail: 'Server is down' }, 500) : ok({ ...SET, in_project: false }))))
    render(<LanguageDialog videoId="p1" filename="a.mp4" onClose={() => {}} onMade={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server is down')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('language-needs-project')).toHaveTextContent('Move this video into a project first')
    expect(screen.queryByRole('button', { name: /Make/ })).toBeNull()
  })

  it('shows a refusal from the server and keeps the dialog open', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return ok(SET)
      const body = JSON.parse(String(init?.body))
      return body.dry_run ? ok({ gate: gate(1), batch_id: null, children: [] }, 201) : ok({ detail: 'This batch may spend up to $0.50, past its ceiling.' }, 409)
    }))
    const made = vi.fn()
    render(<LanguageDialog videoId="p1" filename="a.mp4" onClose={() => {}} onMade={made} />)
    await userEvent.click(await screen.findByRole('checkbox', { name: /Hindi/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Make 1 version' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('past its ceiling')
    expect(made).not.toHaveBeenCalled()
  })

  it('chips mark a version out of sync; Sync this change starts the sync', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { calls.push(`${init?.method} ${url}`); return ok({ job_id: 'T1', lines: [], to: 9 }, 202) }))
    render(<><LanguageChips languages={[{ video_id: 'p2', language: 'hi', label: 'Hindi', out_of_sync: true }, { video_id: 'p3', language: 'ta', label: 'Tamil', out_of_sync: false }]} /><SyncChip videoId="p2" /></>)
    expect(screen.getByRole('link', { name: 'Hindi version, out of sync with master' })).toHaveAttribute('href', '#v/p2')
    expect(screen.getByRole('link', { name: 'Tamil version' })).toBeInTheDocument()
    expect(screen.getByText('Out of sync with master')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sync this change' }))
    expect(await screen.findByText('Syncing the changed lines…')).toBeInTheDocument()
    expect(calls[0]).toMatch(/POST .*\/videos\/p2\/sync$/)
  })

  it('clears the syncing note when the sync turn ends, and says why when it failed', async () => {
    let status = 'running'
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return ok({ job_id: 'T1', lines: [], to: 9 }, 202)
      if (String(url).endsWith('/jobs/T1')) return ok({ job_id: 'T1', kind: 'turn', project_id: 'p2', status, progress: 0, step: '', attempts: 1, result: null, error: status === 'failed' ? 'The voice service is down.' : null })
      return ok({})
    }))
    const settled = vi.fn()
    render(<SyncChip videoId="p2" onSettled={settled} />)
    await userEvent.click(screen.getByRole('button', { name: 'Sync this change' }))
    expect(await screen.findByText('Syncing the changed lines…')).toBeInTheDocument()
    status = 'succeeded'
    await waitFor(() => expect(settled).toHaveBeenCalledWith(true), { timeout: 4000 })
    expect(screen.queryByText('Syncing the changed lines…')).not.toBeInTheDocument()
    status = 'failed'
    await userEvent.click(screen.getByRole('button', { name: 'Sync this change' }))
    expect(await screen.findByRole('alert', {}, { timeout: 4000 })).toHaveTextContent('The sync did not finish. The voice service is down.')
    expect(settled).toHaveBeenLastCalledWith(false)
    expect(screen.getByRole('button', { name: 'Sync this change' })).toBeInTheDocument()
  })
})

describe('B2: brand names and translations in Words', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('adds a brand word that never translates', async () => {
    const { ProjectWords } = await import('./ProjectWords')
    const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return ok({ rules: [] })
      posts.push(String(init?.body))
      return ok({ rule_id: 1, project_id: 'f1', kind: 'pronounce', data: JSON.parse(String(init?.body)).data, version: 1, created_by: 'local', updated_at: '' }, 201)
    }))
    render(<ProjectWords projectId="f1" languages />)
    await userEvent.type(await screen.findByLabelText('Term'), 'Bhajicam')
    await userEvent.type(screen.getByLabelText('How to say it'), 'bhaji cam')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Brand name, never translate' }))
    await userEvent.click(screen.getByRole('button', { name: '+ Add word' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(JSON.parse(posts[0]).data).toEqual({ term: 'Bhajicam', say: 'bhaji cam', brand: true })
    expect(await screen.findByText('Brand')).toBeInTheDocument()
  })
})
