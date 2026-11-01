import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { ApiError, postTurn, setConsentAsker, startBatchExport } from '../api'
import { ATTEST, EXPORT, LEARN_MORE, LINE, VOICES, attestTitle, exportTitle, keptWhy, refusalKind, speakerName } from './copy'
import { AttestationModal } from './AttestationModal'
import { ExportReminder } from './ExportReminder'
import { ConsentHost } from './ConsentHost'
import { ConsentContext, OFF, type ConsentState } from './context'
import { AttestationCard, LineRefusal, RefusalNote } from './LineRefusal'
import { ProveVoice } from './ProveVoice'
import { VoltagePane } from '../components/VoltagePane'
import { LineDoc } from '../components/LineDoc'
import type { AttestationFacts, ExportFacts } from './types'
import type { ChatMessage, PlanItem, PlanQuestion } from '../types'

const FACTS: AttestationFacts = { code: 'attestation_required', voice: 'v-clone', voice_id: 'v-clone', video_id: 'p1', speaker_label: 'A', speaker_name: 'Asha', statement_version: '2026-10-31' }
const EXPORTING: ExportFacts = { code: 'export_confirm_required', export_ref: 'ex_1', voices: [{ voice_id: 'v-clone', video_id: 'p1', speaker_label: 'A', speaker_name: 'Asha' }], videos: ['p1'], label_default: true }
const BLOCKED = "I can't voice this line. It asks for payment details, which we don't allow."

type Answer = { status: number; body: unknown }
/** fetch, scripted by "METHOD path" (first match wins; a list answers in turn). */
function serve(routes: Record<string, Answer | Answer[]>) {
  const calls: { key: string; body: unknown }[] = []
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace(/^\/api/, '').split('?')[0]}`
    calls.push({ key, body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body ?? null })
    const hit = Object.entries(routes).find(([k]) => k === key)
    if (!hit) return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
    const answers = hit[1]
    const a = Array.isArray(answers) ? (answers.length > 1 ? answers.shift()! : answers[0]) : answers
    return new Response(JSON.stringify(a.body), { status: a.status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return calls
}
const on = (over: Partial<ConsentState> = {}) => ({ children }: { children: ReactNode }) => (
  <ConsentContext.Provider value={{ ...OFF, on: true, ...over }}>{children}</ConsentContext.Provider>
)

beforeEach(() => setConsentAsker(null))
afterEach(() => { vi.unstubAllGlobals(); setConsentAsker(null) })

describe('the plan\'s copy', () => {
  it('names the speaker in the titles, word for word', () => {
    expect(attestTitle(FACTS)).toBe("Use Asha's voice?")
    expect(attestTitle({ speaker_name: null, speaker_label: '2' })).toBe("Use Speaker 2's voice?")
    expect(speakerName({ speaker_name: '', speaker_label: '_' })).toBe('this speaker')
    expect(exportTitle(EXPORTING.voices)).toBe("This video has AI changes to Asha's voice")
    expect(exportTitle([...EXPORTING.voices, { voice_id: 'v2', video_id: 'p1', speaker_label: 'B', speaker_name: 'Ravi' }]))
      .toBe("This video has AI changes to Asha's and Ravi's voices")
    expect(ATTEST.confirm).toMatch(/^I confirm I have the rights and consent to use this voice\. I won't use it to deceive, impersonate or harm anyone, and I'm responsible for how it's used\.$/)
    expect(EXPORT.label).toBe('Add an "AI voice" label to the video (recommended)')
    for (const text of [...Object.values(ATTEST).flat().map((x) => (typeof x === 'string' ? x : x.label)), ...Object.values(EXPORT), ...Object.values(LINE), ...Object.values(VOICES)]) {
      expect(text).not.toMatch(/\u2014/)
    }
  })

  it('reads a line refusal from the guard\'s words or code', () => {
    expect(refusalKind(BLOCKED)).toBe('blocked')
    expect(refusalKind(LINE.held)).toBe('held')
    expect(refusalKind(LINE.suspended)).toBe('suspended')
    expect(refusalKind('anything', 'line_in_review')).toBe('held')
    expect(refusalKind('The voice service was busy.')).toBeNull()
    expect(keptWhy({ saved: false, status: 'failed', reason: 'The voice did not match.' })).toBe('Kept for this video only. The voice did not match.')
    expect(keptWhy({ saved: false, status: 'review', reason: '' })).toBe('Kept for this video only while a person checks your recording.')
  })
})

describe('AttestationModal', () => {
  it('keeps Use this voice off until a choice and the box, then posts the attestation', async () => {
    const calls = serve({ 'POST /videos/p1/voices/v-clone/attest': { status: 201, body: { id: 'va_1' } } })
    const onDone = vi.fn()
    render(<AttestationModal facts={FACTS} onDone={onDone} onCancel={() => {}} />)
    const dialog = screen.getByRole('dialog', { name: "Use Asha's voice?" })
    expect(dialog).toHaveTextContent(ATTEST.body)
    expect(dialog).toHaveTextContent(ATTEST.warning)
    expect(screen.getByRole('heading', { name: "Use Asha's voice?" })).toHaveFocus()
    const accept = screen.getByRole('button', { name: 'Use this voice' })
    expect(accept).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: 'This is my voice' }))
    expect(accept).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: ATTEST.confirm }))
    expect(accept).toBeEnabled()
    await userEvent.click(screen.getByRole('radio', { name: ATTEST.choices[1].label }))
    await userEvent.click(accept)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(calls[0]).toEqual({ key: 'POST /videos/p1/voices/v-clone/attest', body: { choice: 'have_permission', statement_version: '2026-10-31' } })
  })

  it('Escape cancels; the radios are a labelled group reached by keyboard', async () => {
    const onCancel = vi.fn()
    render(<AttestationModal facts={FACTS} onDone={() => {}} onCancel={onCancel} />)
    expect(screen.getByRole('group', { name: 'Whose voice is it?' })).toBeInTheDocument()
    await userEvent.tab()
    expect(screen.getByRole('radio', { name: 'This is my voice' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalled()
  })

  it('says so when the wording changed, and asks for the choice again', async () => {
    serve({ 'POST /videos/p1/voices/v-clone/attest': { status: 409, body: { detail: { code: 'statement_changed', message: 'The wording has changed since you opened it. Read it again and confirm.' } } } })
    render(<AttestationModal facts={FACTS} onDone={() => {}} onCancel={() => {}} />)
    await userEvent.click(screen.getByRole('radio', { name: 'This is my voice' }))
    await userEvent.click(screen.getByRole('checkbox', { name: ATTEST.confirm }))
    await userEvent.click(screen.getByRole('button', { name: 'Use this voice' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The wording has changed')
    expect(screen.getByRole('button', { name: 'Use this voice' })).toBeDisabled()
  })
})

describe('ExportReminder', () => {
  it('has the label ticked, needs the permission box, and posts the label choice', async () => {
    const calls = serve({ 'POST /exports/ex_1/confirm': { status: 201, body: { id: 'ea_1', label_on: false } } })
    const onDone = vi.fn()
    render(<ExportReminder facts={EXPORTING} onDone={onDone} onBack={() => {}} />)
    expect(screen.getByRole('dialog', { name: "This video has AI changes to Asha's voice" })).toBeInTheDocument()
    const label = screen.getByRole('checkbox', { name: EXPORT.label })
    expect(label).toBeChecked()
    const go = screen.getByRole('button', { name: 'Export' })
    expect(go).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: EXPORT.confirm }))
    await userEvent.click(label)
    await userEvent.click(go)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(calls[0]).toEqual({ key: 'POST /exports/ex_1/confirm', body: { label_on: false } })
  })

  it('Back and Escape leave the export unmade', async () => {
    const onBack = vi.fn()
    render(<ExportReminder facts={EXPORTING} onDone={() => {}} onBack={onBack} />)
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    await userEvent.keyboard('{Escape}')
    expect(onBack).toHaveBeenCalledTimes(2)
  })
})

describe('the guard\'s 409s, from any request', () => {
  const asked = { status: 409, body: { detail: FACTS } }
  const made = { status: 202, body: { job_id: 'J1' } }

  it('asks, then sends the same request again once the person confirms', async () => {
    const calls = serve({ 'POST /videos/p1/turns': [asked, made] })
    const asker = vi.fn(async () => true)
    setConsentAsker(asker)
    await expect(postTurn('p1', 'voice it')).resolves.toMatchObject({ job_id: 'J1' })
    expect(asker).toHaveBeenCalledWith({ kind: 'attestation', facts: expect.objectContaining({ voice: 'v-clone' }) })
    expect(calls.map((c) => c.key)).toEqual(['POST /videos/p1/turns', 'POST /videos/p1/turns'])
    expect(calls[1].body).toEqual(calls[0].body)
  })

  it('a cancel is the plain refusal, and with nothing installed (flag off) nothing is asked', async () => {
    serve({ 'POST /videos/p1/turns': asked })
    setConsentAsker(async () => false)
    await expect(postTurn('p1', 'voice it')).rejects.toBeInstanceOf(ApiError)
    setConsentAsker(null)
    const err = await postTurn('p1', 'voice it').catch((e) => e)
    expect(err.status).toBe(409)
  })

  it('a batch export asks once for the whole batch', async () => {
    const calls = serve({ 'POST /projects/f1/exports': [{ status: 409, body: { detail: { ...EXPORTING, videos: ['p1', 'p2', 'p3'] } } }, { status: 201, body: { export_id: 'E1' } }] })
    const asker = vi.fn(async () => true)
    setConsentAsker(asker)
    await startBatchExport('f1', { video_ids: ['p1', 'p2', 'p3'], preset_ids: [1] })
    expect(asker).toHaveBeenCalledTimes(1)
    expect(asker.mock.calls[0]).toEqual([{ kind: 'export', facts: expect.objectContaining({ export_ref: 'ex_1' }) }])
    expect(calls).toHaveLength(2)
  })
})

describe('ConsentHost', () => {
  it('opens the modal for a 409 anywhere, then the request goes through', async () => {
    serve({
      'POST /videos/p1/turns': [{ status: 409, body: { detail: FACTS } }, { status: 202, body: { job_id: 'J1' } }],
      'POST /videos/p1/voices/v-clone/attest': { status: 201, body: { id: 'va_1' } },
      'GET /voices/scopes': { status: 200, body: { voices: [] } },
    })
    render(<ConsentHost forceOn><span>editor</span></ConsentHost>)
    let done: unknown = null
    await act(async () => { void postTurn('p1', 'voice it').then((r) => { done = r }) })
    const dialog = await screen.findByRole('dialog', { name: "Use Asha's voice?" })
    await userEvent.click(within(dialog).getByRole('radio', { name: 'This is my voice' }))
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Use this voice' }))
    await waitFor(() => expect(done).toMatchObject({ job_id: 'J1' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('with the flag off installs nothing', async () => {
    serve({ 'POST /videos/p1/turns': { status: 409, body: { detail: FACTS } } })
    render(<ConsentHost forceOn={false}><span>editor</span></ConsentHost>)
    await expect(postTurn('p1', 'voice it')).rejects.toBeInstanceOf(ApiError)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('clears a held line once its notification arrives', async () => {
    serve({
      'GET /voices/scopes': { status: 200, body: { voices: [] } },
      'GET /me/notifications': [
        { status: 200, body: { items: [], unread: 0 } },
        { status: 200, body: { items: [{ id: 1, kind: 'line_decided', title: 'Your held line was cleared. You can voice it now.', body: 'Guaranteed returns.', link: '#v/p1', video_id: 'p1', project_id: null, created_at: '', read: false }], unread: 1 } },
      ],
    })
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const onRetry = vi.fn()
      render(<ConsentHost forceOn><LineRefusal reason={LINE.held} videoId="p1" words="Guaranteed returns." onRetry={onRetry} /></ConsentHost>)
      expect(screen.getByTestId('line-held')).toHaveAttribute('data-state', 'held')
      expect(screen.getByTestId('line-refusal-text')).toHaveTextContent(LINE.held)
      await act(async () => { await vi.advanceTimersByTimeAsync(16_000) })
      await waitFor(() => expect(screen.getByTestId('line-held')).toHaveAttribute('data-state', 'cleared'))
      await userEvent.click(screen.getByRole('button', { name: 'Voice it now' }))
      expect(onRetry).toHaveBeenCalled()
    } finally { vi.useRealTimers() }
  })
})

describe('LineRefusal and the chat', () => {
  it('a blocked line says why with Edit the line; suspended says the plan\'s words; flag off shows nothing', async () => {
    const onEdit = vi.fn()
    const { unmount } = render(<LineRefusal reason={BLOCKED} onEdit={onEdit} />, { wrapper: on() })
    expect(screen.getByTestId('line-blocked')).toHaveTextContent(BLOCKED)
    await userEvent.click(screen.getByRole('button', { name: 'Edit the line' }))
    expect(onEdit).toHaveBeenCalled()
    unmount()
    render(<LineRefusal reason={LINE.suspended} />, { wrapper: on() })
    expect(screen.getByTestId('line-suspended')).toHaveTextContent(LINE.suspended)
    const off = render(<LineRefusal reason={BLOCKED} />)
    expect(off.container).toBeEmptyDOMElement()
  })

  it('a held line that was not cleared says so, with Edit the line', () => {
    render(<LineRefusal reason={LINE.held} videoId="p1" words="x" onEdit={() => {}} />,
      { wrapper: on({ decisionFor: () => ({ cleared: false, title: 'Your held line was not cleared.' }) }) })
    expect(screen.getByTestId('line-held')).toHaveAttribute('data-state', 'not-cleared')
    expect(screen.getByRole('button', { name: 'Edit the line' })).toBeInTheDocument()
  })

  it('Edit the line in the chat asks the transcript to open that line', async () => {
    const seen = vi.fn()
    window.addEventListener('voltage:edit-line', seen)
    render(<RefusalNote refusal={{ code: 'line_blocked', message: BLOCKED, start: 7.54, end: 9.02 }} />, { wrapper: on() })
    await userEvent.click(screen.getByRole('button', { name: 'Edit the line' }))
    expect((seen.mock.calls[0][0] as CustomEvent).detail).toEqual({ start: 7.54, end: 9.02 })
    window.removeEventListener('voltage:edit-line', seen)
  })

  it('the pane shows a step\'s refusal whole, and the turn\'s attestation card inline', async () => {
    const calls = serve({ 'POST /videos/p1/voices/v-clone/attest': { status: 201, body: { id: 'va_1' } } })
    const thread: ChatMessage[] = [
      { role: 'user', text: 'Ask for the OTP', seq: 1 },
      { role: 'assistant', text: 'Could not voice “Share the OTP”: I can\'t voice this line.', kind: 'step', seq: 2, data: { tool: 'synthesize_take', refusal: { code: 'line_blocked', message: BLOCKED, start: 7.54, end: 9.02 } } },
    ]
    const question: PlanQuestion = { text: "Use Asha's voice?", options: ['Use this voice', 'Cancel'], guess: 'Use this voice', gate: false, kind: 'attestation_required', attestation: FACTS }
    const onAnswer = vi.fn()
    render(<VoltagePane messages={thread} projectId="p1" state="ready" question={question} onAnswer={onAnswer} onSubmit={() => {}} />, { wrapper: on() })
    expect(screen.getByTestId('refusal-note')).toHaveTextContent(BLOCKED)
    const card = screen.getByTestId('attestation-card')
    expect(within(card).getByText("Use Asha's voice?")).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('radio', { name: 'This is my voice' }))
    await userEvent.click(within(card).getByRole('checkbox'))
    await userEvent.click(within(card).getByRole('button', { name: 'Use this voice' }))
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('Use this voice'))
    expect(calls[0].key).toBe('POST /videos/p1/voices/v-clone/attest')
  })

  it('Cancel on the card answers Cancel; with the flag off the pane shows the plain question', async () => {
    const question: PlanQuestion = { text: "Use Asha's voice?", options: ['Use this voice', 'Cancel'], guess: 'Use this voice', gate: false, kind: 'attestation_required', attestation: FACTS }
    const onAnswer = vi.fn()
    const { unmount } = render(<AttestationCard facts={FACTS} onAnswer={onAnswer} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onAnswer).toHaveBeenCalledWith('Cancel')
    unmount()
    render(<VoltagePane messages={[]} state="ready" question={question} onSubmit={() => {}} />)
    expect(screen.queryByTestId('attestation-card')).not.toBeInTheDocument()
    expect(screen.getByTestId('clarify')).toHaveTextContent("Use Asha's voice?")
  })
})

describe('the line in the transcript', () => {
  const STATEMENTS = [{ text: 'Start a live Bajicam session.', start: 7.54, end: 9.02, speaker: 'A' }]
  const blocked: PlanItem = {
    item_id: 'i1', selection: { start: 7.54, end: 9.02 }, old_text: 'Start a live Bajicam session.', new_text: 'Share the OTP you got.',
    speaker: 'A', mix: 'replace', reason: '', kind: 'planned', enabled: true, status: 'failed', fit: null, candidate: null,
    edit_id: null, question: null, error: BLOCKED, note: null, progress: null,
  }
  const handlers = { onSeek: vi.fn(), onHear: vi.fn(), onAdd: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onRemove: vi.fn(), onHearTake: vi.fn() }

  it('a blocked line shows the guard\'s words, and Edit the line opens the editor on its current words', async () => {
    render(<LineDoc statements={STATEMENTS} currentTime={0} items={[blocked]} {...handlers} />, { wrapper: on() })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(within(row).getByTestId('line-blocked')).toHaveTextContent(BLOCKED)
    await userEvent.click(within(row).getByRole('button', { name: 'Edit the line' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Share the OTP you got.')
  })

  it('[Edit the line] from the chat opens the same editor; the flag off keeps the plain Failed row', async () => {
    const { unmount } = render(<LineDoc statements={STATEMENTS} currentTime={0} items={[blocked]} {...handlers} />, { wrapper: on() })
    act(() => { window.dispatchEvent(new CustomEvent('voltage:edit-line', { detail: { start: 7.54 } })) })
    expect(await screen.findByRole('textbox', { name: /new wording/i })).toHaveValue('Share the OTP you got.')
    unmount()
    render(<LineDoc statements={STATEMENTS} currentTime={0} items={[blocked]} {...handlers} onRetry={() => {}} />)
    expect(screen.queryByTestId('line-blocked')).not.toBeInTheDocument()
    expect(screen.getByTestId('failed-reason')).toHaveTextContent(BLOCKED)
  })

  it('a video-only voice is tagged in the picker, and from another video says it cannot be used here', async () => {
    const VOICES_ = [{ voice_id: 'v-clone', name: 'Asha', description: '', gender: null, accent: null, age: null }]
    const scopeOf = (id: string | null | undefined) => (id === 'v-clone' ? { voice_id: 'v-clone', scope: 'video' as const, status: 'active' as const, kind: 'cloned', source_video_id: 'p9', speaker_label: 'A', video_only: true, verified: false } : null)
    render(<LineDoc statements={STATEMENTS} currentTime={0} voices={VOICES_} videoId="p1" family={['p1']} {...handlers} />, { wrapper: on({ scopeOf }) })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Edit it' }))
    const picker = screen.getByRole('combobox', { name: 'Voice' })
    expect(within(picker).getByRole('option', { name: /Asha · This video only/ })).toBeInTheDocument()
    await userEvent.selectOptions(picker, 'v-clone')
    expect(screen.getByTestId('voice-out-of-scope')).toHaveTextContent(LINE.outOfScope)
  })
})

describe('ProveVoice', () => {
  const scope = { voice_id: 'v-clone', scope: 'video' as const, status: 'active' as const, kind: 'cloned', source_video_id: 'p1', speaker_label: 'A', video_only: true, verified: false }

  it('is titled Prove it\'s your voice; a pass promotes the voice', async () => {
    const calls = serve({
      'POST /videos/p1/liveness': { status: 200, body: { attempt_id: 'cv_1', sentence: 'Purple kettle river.', status: 'passed', reason: 'The voice matched.', tip: '', test_mode: false, verified: true } },
      'POST /voices/v-clone/promote': { status: 200, body: { ...scope, scope: 'library', video_only: false, verified: true } },
    })
    const onClose = vi.fn()
    render(<ProveVoice name="Asha" scope={scope} onClose={onClose} />)
    expect(screen.getByRole('dialog', { name: "Prove it's your voice" })).toBeInTheDocument()
    expect(await screen.findByTestId('prove-outcome')).toHaveTextContent('Saved. Asha is in My voices now.')
    expect(calls.map((c) => c.key)).toContain('POST /voices/v-clone/promote')
    expect(calls.find((c) => c.key === 'POST /videos/p1/liveness')?.body).toEqual({ speaker: 'A' })
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalledWith({ saved: true })
  })

  it('review or a fail keeps it for this video, with the reason', async () => {
    const calls = serve({ 'POST /videos/p1/liveness': { status: 200, body: { attempt_id: 'cv_2', sentence: 'x', status: 'failed', reason: 'The voice did not match the speaker.', tip: '', test_mode: false, verified: true } } })
    const onClose = vi.fn()
    render(<ProveVoice name="Asha" scope={scope} onClose={onClose} />)
    expect(await screen.findByTestId('prove-outcome')).toHaveTextContent('Kept for this video only. The voice did not match the speaker.')
    expect(calls.map((c) => c.key)).not.toContain('POST /voices/v-clone/promote')
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalledWith({ saved: false, status: 'failed', reason: 'The voice did not match the speaker.' })
  })
})

describe('Learn more (step 8)', () => {
  it('the modal and the reminder link to Help\'s Using voices responsibly in a new tab, before the buttons', async () => {
    const { readFileSync, existsSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const article = resolve(__dirname, `../../../help/articles/voices/${LEARN_MORE.slug}.md`)
    expect(existsSync(article)).toBe(true)
    expect(readFileSync(article, 'utf8')).toMatch(/^---\ntitle: Using voices responsibly\n/)
    const { unmount } = render(<AttestationModal facts={FACTS} onDone={() => {}} onCancel={() => {}} />)
    const inModal = screen.getByRole('link', { name: /Learn more about using voices responsibly/ })
    expect(inModal).toHaveAttribute('href', `#help/${LEARN_MORE.slug}`)
    expect(inModal).toHaveAttribute('target', '_blank')
    expect(screen.getByTestId('attest-warning')).toHaveTextContent(ATTEST.warning)          // the plan's words, intact
    expect(inModal.compareDocumentPosition(screen.getByRole('button', { name: 'Use this voice' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    unmount()
    render(<ExportReminder facts={EXPORTING} onDone={() => {}} onBack={() => {}} />)
    const link = screen.getByRole('link', { name: /Learn more about using voices responsibly/ })
    expect(link).toHaveAttribute('href', `#help/${LEARN_MORE.slug}`)
    expect(link.compareDocumentPosition(screen.getByRole('button', { name: 'Export' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('the server holds the same words', () => {
  it('every sentence of the copy is in the voice guard (app/safety/voice_guard.py)', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const guard = readFileSync(resolve(__dirname, '../../../backend/app/safety/voice_guard.py'), 'utf8').replace(/"\s*\n\s*"/g, '').replace(/\\"/g, '"')
    const words = [ATTEST.body, ATTEST.warning, ATTEST.cancel, ATTEST.accept, ATTEST.confirm, ...ATTEST.choices.map((c) => c.label),
      EXPORT.label, EXPORT.confirm, EXPORT.back, EXPORT.accept, LINE.held, LINE.suspended, LINE.outOfScope, BLOCKED]
    for (const w of words) expect(guard, w).toContain(w)
  })
})
