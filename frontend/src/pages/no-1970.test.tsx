/** Bug 2: no rendered page shows epoch zero, whatever a date field holds. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { ProjectsPage } from './ProjectsPage'
import { VoicesPage } from './VoicesPage'
import { ExportPage } from './ExportPage'
import { ProjectPage } from './ProjectPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
// Every shape a date ever arrived in: null, zero, a boolean, seconds, an empty string, garbage.
const ODD = [null, 0, true, false, 1760884325, '', 'soon'] as unknown as string[]
const MEDIA = { kind: 'video', sha256: 'm'.repeat(64), duration: 2.3, container: 'mp4' }

function stub() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/usage?period')) return ok({ period: 'month', spent_usd: 0, ceiling_usd: 10, project_cap_usd: 2, turns: 0, takes: 0, voices_made: 0, avg_turn_usd: 0, by_vendor: [], by_video: [], by_project: [] })
    if (url.endsWith('/voices')) return ok({ default: 'c1', voices: [], mine: ODD.map((at, i) => ({ voice_id: `m${i}`, name: `Voice ${i}`, seconds: 12, at, kind: 'recorded', consent_granted_at: at })), project: ODD.map((at, i) => ({ voice_id: `s${i}`, name: `Shared ${i}`, seconds: 0, at, kind: 'recorded', consent: true, consent_granted_at: at, project_id: 'f1', project_name: 'F' })) })
    if (url.endsWith('/voices/made')) return ok({ voices: [] })
    if (url.endsWith('/voices/speakers')) return ok({ speakers: [] })
    if (url.endsWith('/videos/p1/receipt')) return ok({ turns: 0, takes: 0, spent_usd: 0, changes: [], drafts: 0, render: { sha256: 'r'.repeat(64), duration: 2.3, filename: 'x.mp4', at: 0 } })
    if (url.endsWith('/videos/p1')) return ok({ video_id: 'p1', filename: 'x.mp4', duration: 2.3, media: MEDIA, consent_granted_at: true, created_at: 0, transcript: [], edits: [], messages: [] })
    if (url.endsWith('/projects/f1')) return ok({ project: { project_id: 'f1', name: 'F', brief: '', ceiling_usd: null, spent_usd: 0, created_at: null }, videos: [], files: ODD.map((at, i) => ({ name: `f${i}.txt`, sha256: String(i).repeat(64), size: 1, kind: 'txt', at })), suggestions: [], voices: ODD.map((at, i) => ({ voice_id: `v${i}`, name: `Voice ${i}`, kind: 'recorded', seconds: 1, at, consent: true, consent_granted_at: at })) })
    return ok({})
  }))
}

describe('no page shows 1970 (bug 2)', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('Home, with odd created_at values', () => {
    stub()
    const videos = ODD.map((at, i) => ({ video_id: `p${i}`, project_id: null, filename: `v${i}.mp4`, duration: 2, created_at: at, edits: 0 }))
    const { container } = render(<ProjectsPage me={ME} projects={videos} onOpen={() => {}} onUpload={() => {}} onSample={() => {}} onDelete={() => {}} uploading={false} />)
    expect(container.textContent).not.toMatch(/1970/)
  })

  it('Voices, with odd voice and consent dates', async () => {
    stub()
    const { container } = render(<VoicesPage me={ME} />)
    await screen.findByText('Voice 1')
    expect(container.textContent).not.toMatch(/1970/)
  })

  it('a project, with odd file and voice dates', async () => {
    stub()
    const { container } = render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    await screen.findByText('Voice 2')
    expect(container.textContent).not.toMatch(/1970/)
  })

  it('Export, with an odd render date', async () => {
    stub()
    const { container } = render(<ExportPage projectId="p1" me={ME} onBack={() => {}} />)
    await waitFor(() => expect(container.textContent).toMatch(/x\.mp4|sample|Download/i))
    expect(container.textContent).not.toMatch(/1970/)
  })
})
