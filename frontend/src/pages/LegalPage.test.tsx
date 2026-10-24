import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LegalPage, type LegalDoc } from './LegalPage'
import { parseRoute, hrefFor } from '../lib/route'

const DOCS: [LegalDoc, string][] = [
  ['terms', 'Terms of service'], ['privacy', 'Privacy policy'], ['subprocessors', 'Sub-processors'], ['acceptable-use', 'Acceptable use policy'],
]

describe('the policy drafts (G6, v2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it.each(DOCS)('%s carries the draft banner, its contents and the notes for counsel', (doc, title) => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ open: false }) }) as Response))
    render(<LegalPage doc={doc} />)
    expect(screen.getByTestId('legal-draft')).toHaveTextContent('Draft, needs legal review')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title)
    expect(screen.getAllByTestId('legal-counsel').length).toBeGreaterThan(0)
    for (const note of screen.getAllByTestId('legal-counsel')) expect(note).toHaveTextContent(/^For counsel:/)
    const contents = within(screen.getByRole('navigation', { name: 'On this page' })).getAllByRole('button')
    expect(contents.length).toBe(screen.getAllByRole('region').length)
    expect(document.body.textContent).not.toContain('—')
  })

  it('jumps to a section from the contents', async () => {
    Element.prototype.scrollIntoView = vi.fn()
    render(<LegalPage doc="terms" />)
    await userEvent.click(within(screen.getByRole('navigation', { name: 'On this page' })).getByRole('button', { name: 'Refunds' }))
    expect(screen.getByRole('heading', { level: 2, name: 'Refunds' })).toHaveFocus()
  })

  it('lists every outside service, on the Privacy policy and on its own page', () => {
    expect(parseRoute('#subprocessors')).toEqual({ page: 'legal', doc: 'subprocessors' })
    expect(hrefFor({ page: 'legal', doc: 'subprocessors' })).toBe('#subprocessors')
    for (const doc of ['privacy', 'subprocessors'] as const) {
      const { unmount } = render(<LegalPage doc={doc} />)
      const names = within(screen.getByTestId('vendor-list')).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
      expect(names).toEqual(expect.arrayContaining(['Anthropic (Claude)', 'OpenAI (Whisper)', 'ElevenLabs', 'Stripe', 'Razorpay', 'Resend', 'Sentry', 'Google sign-in']))
      unmount()
    }
  })
})
