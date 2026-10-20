import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectWords } from './ProjectWords'
import { termOf } from '../lib/words'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const rule = (rule_id: number, kind: string, data: Record<string, string>) => ({ rule_id, project_id: 'f1', kind, data, version: 1, created_by: 'local', updated_at: '2026-10-20T10:00:00Z' })

function server(start: unknown[] = []) {
  let rules = [...start] as ReturnType<typeof rule>[]
  let next = 10
  const calls: string[] = []
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(`${method} ${url}`)
    if (url.endsWith('/projects/f1/rules') && method === 'GET') return ok({ rules, rules_version: rules.length })
    if (url.endsWith('/projects/f1/rules') && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      const made = rule(next++, body.kind, body.data)
      rules = [...rules, made]
      return ok(made, 201)
    }
    const audio = /\/rules\/(\d+)\/audio$/.exec(url)
    if (audio && method === 'POST') { const id = Number(audio[1]); rules = rules.map((r) => (r.rule_id === id ? { ...r, data: { ...r.data, audio: 'a'.repeat(64) } } : r)); return ok(rules.find((r) => r.rule_id === id)) }
    const one = /\/rules\/(\d+)$/.exec(url)
    if (one && method === 'DELETE') { rules = rules.filter((r) => r.rule_id !== Number(one[1])); return ({ ok: true, status: 204, json: async () => null, text: async () => '' }) as Response }
    throw new Error(`unexpected ${method} ${url}`)
  })
  return { fetcher, calls }
}

describe('A3: the Words section', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists words with how to say them, banned words and required lines', async () => {
    const { fetcher } = server([rule(1, 'pronounce', { term: 'Bhaji Cam', say: 'BAH-jee cam', respell: 'Bah jee cam', audio: 'b'.repeat(64) }), rule(2, 'banned', { word: 'cheap' }), rule(3, 'required_line', { text: 'T&C apply' })])
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectWords projectId="f1" />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the project words…')
    const row = await screen.findByTestId('word-row')
    expect(within(row).getByText('Bhaji Cam')).toBeInTheDocument()
    expect(within(row).getByText('BAH-jee cam')).toBeInTheDocument()
    expect(within(row).getByLabelText('How Bhaji Cam is said')).toHaveAttribute('src', expect.stringContaining('/api/projects/f1/rules/1/audio'))
    expect(within(screen.getByTestId('banned-words')).getByText('cheap')).toBeInTheDocument()
    expect(within(screen.getByTestId('required-lines')).getByText('“T&C apply”')).toBeInTheDocument()
  })

  it('adds a word, a banned word and a required line, and takes one out', async () => {
    const { fetcher, calls } = server()
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectWords projectId="f1" />)
    expect(await screen.findByText(/No words yet/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Term'), 'Bhaji Cam')
    expect(screen.getByRole('button', { name: '+ Add word' })).toBeDisabled()     // how to say it is needed
    await userEvent.type(screen.getByLabelText('How to say it'), 'BAH-jee cam')
    await userEvent.click(screen.getByRole('button', { name: '+ Add word' }))
    expect(await screen.findByTestId('word-row')).toHaveTextContent('Bhaji Cam')
    await userEvent.type(screen.getByLabelText('Banned word'), 'cheap')
    await userEvent.click(within(screen.getByTestId('banned-words')).getByRole('button', { name: '+ Add' }))
    await userEvent.type(screen.getByLabelText('Required line'), 'T&C apply')
    await userEvent.click(within(screen.getByTestId('required-lines')).getByRole('button', { name: '+ Add' }))
    expect(await screen.findByText('“T&C apply”')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove cheap' }))
    await waitFor(() => expect(within(screen.getByTestId('banned-words')).queryByText('cheap')).toBeNull())
    expect(calls.filter((c) => c.startsWith('POST'))).toHaveLength(3)
  })

  it('keeps a clip for a word', async () => {
    const { fetcher } = server([rule(1, 'pronounce', { term: 'Bhaji Cam', say: 'BAH-jee cam' })])
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectWords projectId="f1" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add a clip' }))
    await userEvent.upload(screen.getByLabelText('Choose a clip of the word said right'), new File(['x'], 'say.wav', { type: 'audio/wav' }))
    expect(await screen.findByLabelText('How Bhaji Cam is said')).toBeInTheDocument()
  })

  it('says when the words cannot be read, with a way to try again', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'no' }, 500)))
    render(<ProjectWords projectId="f1" />)
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('termOf (learn a word)', () => {
  it('takes one to four words without the punctuation around them', () => {
    expect(termOf(' Bajicam, ')).toBe('Bajicam')
    expect(termOf('live Bajicam session')).toBe('live Bajicam session')
    expect(termOf('one two three four five')).toBeNull()
    expect(termOf('a\nb')).toBeNull()
    expect(termOf('…')).toBeNull()
  })
})
