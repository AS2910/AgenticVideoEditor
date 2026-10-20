import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from './ProjectsPage'
import { SaveTemplateDialog, TemplatesPage } from './Templates'
import { templateFacts } from '../lib/templates'
import { resetFlags } from '../flags/useFlags'
import type { ProjectTemplate } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
const sum = (extra: Partial<ProjectTemplate['summary']> = {}): ProjectTemplate['summary'] =>
  ({ brief: 'Warm and bright.', rules: 3, words: 1, presets: 2, voices: 0, ceiling_usd: 20, settings: {}, ...extra })
const STARTER: ProjectTemplate = { template_id: 'starter-festive-ad', name: 'Festive ad', starter: true, description: 'A short sale or offer ad for a festival, in several cuts.', summary: sum() }
const MINE: ProjectTemplate = { template_id: 't1', name: 'Diwali ads', starter: false, created_at: '2026-10-20T10:00:00.000Z', summary: sum({ voices: 1, ceiling_usd: null }) }

describe('D1: template facts', () => {
  it('counts what a template carries in one plain line', () => {
    expect(templateFacts(STARTER)).toBe('Brief · 3 rules (1 word) · 2 presets · $20 ceiling')
    expect(templateFacts(MINE)).toBe('Brief · 3 rules (1 word) · 2 presets · 1 voice')
  })
})

describe('D1: Save as template', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks copy or keep for a project voice, then saves with the answer', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body))
      bodies.push(body)
      if (!body.voice) return ok({ detail: 'Dusk belongs to Diwali 2026.', voices: [{ voice_id: 'MADE1', name: 'Dusk' }] }, 409)
      return ok({ ...MINE, name: body.name }, 201)
    }))
    const onSaved = vi.fn()
    render(<SaveTemplateDialog projectId="f1" projectName="Diwali 2026" onClose={vi.fn()} onSaved={onSaved} />)
    const name = screen.getByLabelText('Template name')
    expect(name).toHaveValue('Diwali 2026 template')
    await userEvent.clear(name)
    await userEvent.type(name, 'Diwali ads')
    await userEvent.click(screen.getByRole('button', { name: 'Save template' }))
    const ask = await screen.findByTestId('voice-question')
    expect(ask).toHaveTextContent('Dusk, a voice that belongs to Diwali 2026.')
    await userEvent.click(within(ask).getByRole('radio', { name: 'Keep it in my voices, for any project' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save template' }))
    expect(await screen.findByTestId('template-saved')).toHaveTextContent('Diwali ads.')
    expect(bodies).toEqual([{ name: 'Diwali ads' }, { name: 'Diwali ads', voice: 'keep' }])
    expect(onSaved).toHaveBeenCalled()
  })

  it('says why a save failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'Give the template a name.' }, 422)))
    render(<SaveTemplateDialog projectId="f1" projectName="Diwali" onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Save template' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Give the template a name.')
  })
})

describe('D1: the templates page', () => {
  const calls: string[] = []
  beforeEach(() => {
    calls.length = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url.endsWith('/templates') && method === 'GET') return ok({ templates: [STARTER, MINE] })
      if (url.endsWith('/templates/t1') && method === 'PATCH') return ok({ ...MINE, name: JSON.parse(String(init?.body)).name })
      if (url.endsWith('/templates/t1') && method === 'DELETE') return ({ ok: true, status: 204, text: async () => '' }) as Response
      throw new Error(`unexpected ${method} ${url}`)
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists yours then the starters; renames and deletes yours (asked first); starters have neither', async () => {
    render(<TemplatesPage me={ME} />)
    const mine = await screen.findByTestId('template-t1')
    const starter = screen.getByTestId('template-starter-festive-ad')
    expect(starter).toHaveTextContent('Starter')
    expect(within(starter).queryByRole('button', { name: /Delete|Rename/ })).toBeNull()
    await userEvent.click(within(mine).getByRole('button', { name: 'Rename Diwali ads' }))
    const field = within(mine).getByLabelText('New name')
    await userEvent.clear(field)
    await userEvent.type(field, 'Festival ads')
    await userEvent.click(within(mine).getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(screen.getByTestId('template-t1')).toHaveTextContent('Festival ads'))
    await userEvent.click(within(screen.getByTestId('template-t1')).getByRole('button', { name: 'Delete Festival ads' }))
    expect(screen.getByRole('group', { name: 'Delete Festival ads?' })).toHaveTextContent('Projects made from it keep everything they have.')
    await userEvent.click(screen.getByRole('button', { name: 'Delete template' }))
    await waitFor(() => expect(screen.queryByTestId('template-t1')).toBeNull())
    expect(screen.getByTestId('templates-empty')).toBeInTheDocument()
    expect(calls).toContain('DELETE /api/templates/t1')
  })

  it('shows an error with Try again', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'Down.' }, 500)))
    render(<TemplatesPage me={ME} />)
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('D1: New project from a template on Home', () => {
  beforeEach(() => {
    resetFlags()
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.reuse'] })
      if (url.endsWith('/spend')) return ok({ month: { spent_usd: 0, ceiling_usd: 10, label: 'October' }, binding: null })
      if (url.endsWith('/pins')) return ok({ pins: [] })
      if (url.endsWith('/projects?archived=true')) return ok({ projects: [] })
      if (url.endsWith('/templates')) return ok({ templates: [STARTER, MINE] })
      throw new Error(`unexpected ${url}`)
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('offers Blank or a template and passes the pick on', async () => {
    const onNewFolder = vi.fn(async () => undefined)
    render(<ProjectsPage me={ME} projects={[]} folders={[]} onOpen={vi.fn()} onUpload={vi.fn()} onSample={vi.fn()} onDelete={vi.fn()} onNewFolder={onNewFolder} uploading={false} />)
    await userEvent.click(screen.getByRole('button', { name: '+ New project' }))
    const pick = screen.getByLabelText('Start from')
    await waitFor(() => expect(pick).toBeEnabled())
    expect(Array.from((pick as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(['Blank', 'Diwali ads', 'Festive ad'])
    await userEvent.selectOptions(pick, 'starter-festive-ad')
    expect(screen.getByTestId('start-from-facts')).toHaveTextContent('No videos.')
    await userEvent.type(screen.getByPlaceholderText('Project name'), 'Navratri')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(onNewFolder).toHaveBeenCalledWith('Navratri', 'starter-festive-ad'))
    expect(await screen.findByTestId('templates-link')).toHaveAttribute('href', '#templates')
  })
})
