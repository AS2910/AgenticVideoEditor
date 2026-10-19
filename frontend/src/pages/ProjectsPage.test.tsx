import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from './ProjectsPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const REPORT = { period: 'month', spent_usd: 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14, by_vendor: [], by_project: [] }
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ashish@example.com', name: 'Ashish Sinha', picture: null } }
const OFF = { mode: 'off' as const, user: null }
const PROJECTS = [
  { project_id: 'p2', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: new Date().toISOString(), edits: 1, state: 'draft' as const, last_change: 'Line 2 redone in the Customer’s own voice' },
  { project_id: 'p1', filename: 'goa-beach.mov', duration: 7, created_at: '2025-03-04T08:00:00Z', edits: 0, state: 'shipped' as const },
]

/** Routes by URL: the page itself only asks for this month's spend. */
function routeFetch() {
  return vi.fn(async (url: string) => {
    if (url.includes('/usage?period=month')) return ok(REPORT)
    throw new Error(`unexpected url ${url}`)
  })
}
function setup(props: Partial<Parameters<typeof ProjectsPage>[0]> = {}) {
  const onOpen = vi.fn(), onUpload = vi.fn(), onSample = vi.fn(), onDelete = vi.fn()
  render(<ProjectsPage me={ME} projects={PROJECTS} onOpen={onOpen} onUpload={onUpload} onSample={onSample} onDelete={onDelete} uploading={false} {...props} />)
  return { onOpen, onUpload, onSample, onDelete }
}

describe('ProjectsPage', () => {
  beforeEach(() => vi.stubGlobal('fetch', routeFetch()))
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('greets by name, shows the nav and the account initial, and this month’s spend', async () => {
    setup()
    expect(screen.getByText(/^Good (morning|afternoon|evening), Ashish$/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('What should your next video say?')
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Voices' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Account' })).toHaveTextContent('A')
    expect(await screen.findByTestId('month-spend')).toHaveTextContent(/\$2\.06of \$10 · [A-Z][a-z]{2}/)
  })

  it('lists the recent projects as cards linking to the editor', async () => {
    const { onOpen } = setup()
    expect(screen.getByText('2 projects')).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByText('Exported')).toBeInTheDocument()
    expect(screen.getByText('Line 2 redone in the Customer’s own voice')).toBeInTheDocument()
    expect(screen.getByText('Nothing changed yet')).toBeInTheDocument()
    expect(screen.getByText(/^Today · \d{1,2}:\d{2}$/)).toBeInTheDocument()
    expect(screen.getByText(/^4 Mar( 2025)?$/)).toBeInTheDocument()
    const card = screen.getByRole('link', { name: /bhaji-cam-ad\.mp4/ })
    expect(card).toHaveAttribute('href', '#p2')
    expect(card.querySelector('img')).toHaveAttribute('src', '/api/projects/p2/frames/0')
    await userEvent.click(card)
    expect(onOpen).toHaveBeenCalledWith('p2')
  })

  it('falls back to a plain block when a frame does not load', () => {
    setup()
    const img = screen.getByRole('link', { name: /goa-beach\.mov/ }).querySelector('img')!
    fireEvent.error(img)
    expect(screen.getAllByTestId('frame-fallback')).toHaveLength(1)
  })

  it('hands a chosen or dropped file to onUpload, and the sample to onSample', async () => {
    const { onUpload, onSample } = setup()
    const file = new File(['video-bytes'], 'my-ad.mp4', { type: 'video/mp4' })
    await userEvent.upload(screen.getByLabelText('Choose a video'), file)
    expect(onUpload).toHaveBeenCalledWith(file)
    const zone = screen.getByTestId('drop-zone')
    fireEvent.dragOver(zone)
    expect(zone).toHaveAttribute('data-over', 'true')
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
    expect(onUpload).toHaveBeenCalledTimes(2)
    expect(zone).not.toHaveAttribute('data-over')
    await userEvent.click(screen.getByRole('button', { name: 'Try the sample ad' }))
    expect(onSample).toHaveBeenCalledOnce()
  })

  it('says how the upload is going and shows the rejection reason', () => {
    const { onUpload } = setup({ uploading: true, progress: 0.4, error: 'That file has no video track.' })
    expect(screen.getByRole('status')).toHaveTextContent('Uploading, 40%.')
    expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Try the sample ad' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('That file has no video track.')
    fireEvent.drop(screen.getByTestId('drop-zone'), { dataTransfer: { files: [new File(['x'], 'x.mp4', { type: 'video/mp4' })] } })
    expect(onUpload).not.toHaveBeenCalled()
  })

  it('asks once more before deleting, then waits with Undo', async () => {
    const { onDelete } = setup({ undoMs: 50 })
    await userEvent.click(screen.getByRole('button', { name: 'Delete goa-beach.mov' }))
    expect(onDelete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Keep' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))
    expect(screen.getByRole('status')).toHaveTextContent('Deleted goa-beach.mov')
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('p1'))
  })

  it('can keep the project, or undo within the grace period', async () => {
    const { onDelete } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Delete goa-beach.mov' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(screen.queryByRole('button', { name: 'Delete for good' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete goa-beach.mov' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByRole('link', { name: /goa-beach\.mov/ })).toBeInTheDocument()
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('says hello and shows V when sign-in is off, and where projects will appear when there are none', () => {
    setup({ me: OFF, projects: [] })
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Account' })).toHaveTextContent('V')
    expect(screen.getByText('0 projects')).toBeInTheDocument()
    expect(screen.getByText(/your projects will show here/i)).toBeInTheDocument()
  })
})
