import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from './ProjectsPage'
import { unlabelledMoney } from '../lib/money'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const SPEND = { month: { spent_usd: 2.06, ceiling_usd: 10, label: 'October' }, binding: 'month' }
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ashish@example.com', name: 'Ashish Sinha', picture: null } }
const OFF = { mode: 'off' as const, user: null }
const FOLDERS = [
  { project_id: 'f1', name: 'Diwali 2026', brief: 'Brand is Bhaji Cam.', ceiling_usd: 10, spent_usd: 1.94, created_at: '2026-10-18T08:00:00Z', video_count: 1 },
  { project_id: 'f2', name: 'Goa tourism', brief: '', ceiling_usd: null, spent_usd: 0, created_at: '2026-10-17T08:00:00Z', video_count: 0 },
]
const VIDEOS = [
  { video_id: 'p2', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: new Date().toISOString(), edits: 1, state: 'draft' as const, last_change: 'Line 2 redone in the Customer’s own voice' },
  { video_id: 'p1', project_id: null, filename: 'goa-beach.mov', duration: 7, created_at: '2025-03-04T08:00:00Z', edits: 0, state: 'shipped' as const },
]

/** Routes by URL: the page asks for this month's spend; the move dialog moves a video. */
function routeFetch(moves: { url: string; body: unknown }[] = [], conflict = false) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/api/spend')) return ok(SPEND)
    if (url.endsWith('/videos/p2') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      moves.push({ url, body })
      if (conflict && !body.voice) return ok({ detail: 'This video uses a project voice.', voices: [{ voice_id: 'v9', name: 'Diwali Narrator' }] }, 409)
      return ok({ ...VIDEOS[0], project_id: body.project_id, project_name: body.project_id === 'f2' ? 'Goa tourism' : null })
    }
    throw new Error(`unexpected url ${url}`)
  })
}
function setup(props: Partial<Parameters<typeof ProjectsPage>[0]> = {}) {
  const onOpen = vi.fn(), onUpload = vi.fn(), onSample = vi.fn(), onDelete = vi.fn(), onNewFolder = vi.fn(), onMoved = vi.fn()
  render(<ProjectsPage me={ME} projects={VIDEOS} folders={FOLDERS} onOpen={onOpen} onUpload={onUpload} onSample={onSample} onDelete={onDelete} onNewFolder={onNewFolder} onMoved={onMoved} uploading={false} {...props} />)
  return { onOpen, onUpload, onSample, onDelete, onNewFolder, onMoved }
}

describe('Home (projects as folders)', () => {
  beforeEach(() => vi.stubGlobal('fetch', routeFetch()))
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('shows the nav with Home current, the account initial, this month’s spend, and the projects down the side', async () => {
    setup()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('What should your next video say?')
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Account' })).toHaveTextContent('A')
    // Spend scopes: the monthly scope, named.
    expect(await screen.findByTestId('month-spend')).toHaveTextContent('October: $2.06 of $10')
    expect(unlabelledMoney(document.body)).toEqual([])
    const side = screen.getByTestId('projects-side')
    expect(within(side).getByRole('link', { name: /Diwali 2026/ })).toHaveAttribute('href', '#p/f1')
    expect(within(side).getByRole('link', { name: /Goa tourism/ })).toBeInTheDocument()
    expect(within(side).getByRole('button', { name: /Standalone videos/ })).toHaveTextContent('1')
  })

  it('lists the recent videos as cards with a project chip, filtered by the tabs', async () => {
    const { onOpen } = setup()
    expect(screen.getByRole('tab', { name: 'All · 2' })).toHaveAttribute('aria-selected', 'true')
    const chips = screen.getAllByTestId('project-chip').map((c) => c.textContent)
    expect(chips).toEqual(['Diwali 2026', 'No project'])
    expect(screen.getByText(/^Today · \d{1,2}:\d{2}$/)).toBeInTheDocument()
    const card = screen.getByRole('link', { name: /bhaji-cam-ad\.mp4/ })
    expect(card).toHaveAttribute('href', '#v/p2')
    expect(card.querySelector('img')).toHaveAttribute('src', '/api/videos/p2/frames/0')
    await userEvent.click(card)
    expect(onOpen).toHaveBeenCalledWith('p2')
    await userEvent.click(screen.getByRole('tab', { name: 'No project · 1' }))
    expect(screen.queryByRole('link', { name: /bhaji-cam-ad\.mp4/ })).toBeNull()
    expect(screen.getByRole('link', { name: /goa-beach\.mov/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'In projects · 1' }))
    expect(screen.queryByRole('link', { name: /goa-beach\.mov/ })).toBeNull()
  })

  it('hands a chosen or dropped file to onUpload with the project picked under Add to', async () => {
    const { onUpload, onSample } = setup()
    const file = new File(['video-bytes'], 'my-ad.mp4', { type: 'video/mp4' })
    expect(screen.getByTestId('dest-note')).toHaveTextContent('It will be a standalone video.')
    await userEvent.upload(screen.getByLabelText('Choose a video'), file)
    expect(onUpload).toHaveBeenCalledWith(file, null)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Add to' }), 'f1')
    expect(screen.getByTestId('dest-note')).toHaveTextContent("It joins Diwali 2026 and Voltage reads that project's brief and voices from the first turn.")
    const zone = screen.getByTestId('drop-zone')
    fireEvent.dragOver(zone)
    expect(zone).toHaveAttribute('data-over', 'true')
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
    expect(onUpload).toHaveBeenLastCalledWith(file, 'f1')
    expect(zone).not.toHaveAttribute('data-over')
    await userEvent.click(screen.getByRole('button', { name: 'Try the sample ad' }))
    expect(onSample).toHaveBeenCalledOnce()
  })

  it('makes a new project from the side: label, input and buttons stacked; the new one leads the list, selected', async () => {
    const made = { project_id: 'f3', name: 'Diwali 2026 regional variants', brief: '', ceiling_usd: null, spent_usd: 0, created_at: '2026-10-19T08:00:00Z', video_count: 0 }
    const onNewFolder = vi.fn(async () => made)
    const { rerender } = render(<ProjectsPage me={ME} projects={VIDEOS} folders={FOLDERS} onOpen={vi.fn()} onUpload={vi.fn()} onSample={vi.fn()} onDelete={vi.fn()} onNewFolder={onNewFolder} uploading={false} />)
    await userEvent.click(screen.getByRole('button', { name: '+ New project' }))
    const form = screen.getByRole('form', { name: 'New project' })
    const input = within(form).getByRole('textbox', { name: 'New project' })
    expect(input).toHaveFocus()
    expect(input).toHaveAttribute('placeholder', 'Project name')
    expect(input.className).toMatch(/w-full/)
    expect(input.className).toMatch(/min-w-0/)
    const create = within(form).getByRole('button', { name: 'Create' })
    expect(create).toBeDisabled()
    await userEvent.type(input, 'Diwali 2026 regional variants')
    expect(create).toBeEnabled()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(onNewFolder).toHaveBeenCalledWith('Diwali 2026 regional variants'))
    expect(screen.queryByRole('form', { name: 'New project' })).toBeNull()
    // The caller's list now has it (at the end, as the server orders it); the page puts it first and selected.
    rerender(<ProjectsPage me={ME} projects={VIDEOS} folders={[...FOLDERS, made]} onOpen={vi.fn()} onUpload={vi.fn()} onSample={vi.fn()} onDelete={vi.fn()} onNewFolder={onNewFolder} uploading={false} />)
    const links = within(screen.getByTestId('projects-side')).getAllByRole('link')
    expect(links[0]).toHaveTextContent('Diwali 2026 regional variants')
    expect(links[0]).toHaveAttribute('aria-current', 'true')
    expect(links[0]).toHaveAttribute('title', 'Diwali 2026 regional variants')
    expect(links[1]).not.toHaveAttribute('aria-current')
  })

  it('cancels the new project on Escape or Cancel, and never creates an empty one', async () => {
    const { onNewFolder } = setup()
    await userEvent.click(screen.getByRole('button', { name: '+ New project' }))
    await userEvent.keyboard('{Enter}')
    expect(onNewFolder).not.toHaveBeenCalled()
    await userEvent.type(screen.getByRole('textbox', { name: 'New project' }), 'Half a name{Escape}')
    expect(screen.queryByRole('form', { name: 'New project' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '+ New project' }))
    expect(screen.getByRole('textbox', { name: 'New project' })).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('form', { name: 'New project' })).toBeNull()
    expect(screen.getByRole('button', { name: '+ New project' })).toBeInTheDocument()
    expect(onNewFolder).not.toHaveBeenCalled()
  })

  it('says how the upload is going and shows the rejection reason', () => {
    const { onUpload } = setup({ uploading: true, progress: 0.4, error: 'That file has no video track.' })
    expect(screen.getByRole('status')).toHaveTextContent('Uploading, 40%.')
    expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('That file has no video track.')
    fireEvent.drop(screen.getByTestId('drop-zone'), { dataTransfer: { files: [new File(['x'], 'x.mp4', { type: 'video/mp4' })] } })
    expect(onUpload).not.toHaveBeenCalled()
  })

  it('deletes from the card’s menu: asks once more, then waits with Undo', async () => {
    const { onDelete } = setup({ undoMs: 50 })
    await userEvent.click(screen.getByRole('button', { name: 'More for goa-beach.mov' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete…' }))
    expect(onDelete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Keep' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))
    expect(screen.getByRole('status')).toHaveTextContent('Deleted goa-beach.mov')
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('p1'))
  })

  it('moves a video from the card’s menu: the dialog lists the projects and No project, and a toast says where it went', async () => {
    const moves: { url: string; body: unknown }[] = []
    vi.stubGlobal('fetch', routeFetch(moves))
    const { onMoved } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'More for bhaji-cam-ad.mp4' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '↗ Move to project…' }))
    const dialog = screen.getByRole('dialog', { name: 'Move to project' })
    expect(dialog).toHaveTextContent('Now in Diwali 2026.')
    expect(within(dialog).getByRole('radio', { name: /Diwali 2026/ })).toHaveAttribute('aria-checked', 'true')
    expect(within(dialog).getByRole('button', { name: 'Keep it here' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('radio', { name: /No project/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove from project' }))
    await waitFor(() => expect(moves).toEqual([{ url: '/api/videos/p2', body: { project_id: null } }]))
    expect(await screen.findByRole('status')).toHaveTextContent('bhaji-cam-ad.mp4 is now a standalone video.')
    expect(onMoved).toHaveBeenCalledWith('p2', null)
  })

  it('asks about a project voice when the server says one is in use, and answers with the choice', async () => {
    const moves: { url: string; body: unknown }[] = []
    vi.stubGlobal('fetch', routeFetch(moves, true))
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'More for bhaji-cam-ad.mp4' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '↗ Move to project…' }))
    const dialog = screen.getByRole('dialog', { name: 'Move to project' })
    await userEvent.click(within(dialog).getByRole('radio', { name: /Goa tourism/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move to Goa tourism' }))
    const ask = await screen.findByTestId('voice-question')
    expect(ask).toHaveTextContent('This video uses Diwali Narrator, a voice that belongs to Diwali 2026.')
    await userEvent.click(within(ask).getByRole('radio', { name: 'Keep it in my voices, for any project' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move to Goa tourism' }))
    await waitFor(() => expect(moves.at(-1)?.body).toEqual({ project_id: 'f2', voice: 'keep' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Moved bhaji-cam-ad.mp4 to Goa tourism.')
  })

  it('shows V when sign-in is off, and where videos will appear when there are none', () => {
    setup({ me: OFF, projects: [], folders: [] })
    expect(screen.getByRole('link', { name: 'Account' })).toHaveTextContent('V')
    expect(screen.getByText(/your videos will show here/i)).toBeInTheDocument()
    expect(screen.getByText(/A project holds videos that share/)).toBeInTheDocument()
  })
})
