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

  it('marks the voice consent sections as new drafts, and leaves the grievance officer to the owner (v3)', () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ open: false }) }) as Response))
    const sectionsOf = (doc: LegalDoc) => {
      const { unmount } = render(<LegalPage doc={doc} />)
      const marked = screen.getAllByTestId('legal-section-draft').map((stamp) => stamp.closest('section')!.querySelector('h2')!.textContent)
      const text = document.body.textContent ?? ''
      unmount()
      return { marked, text }
    }
    const terms = sectionsOf('terms')
    expect(terms.marked).toEqual(expect.arrayContaining(['Voices and consent', 'Suspending and deleting voices', 'Records we keep about voices', 'What Voltage makes', 'Your responsibility to us']))
    expect(terms.text).toContain('indemnify us')
    expect(terms.text).toMatch(/for 7 years/)
    expect(terms.text).toMatch(/for 2 years/)
    const aup = sectionsOf('acceptable-use')
    expect(aup.marked).toEqual(expect.arrayContaining(['Lines we check', 'Grievance Officer', 'No fraud', 'Elections and public life']))
    expect(aup.text).toContain('No robocalls')
    expect(aup.text).toContain('Name: [Grievance Officer name]')
    expect(aup.text).toContain('Email: [Grievance Officer email]')
    expect(screen.queryByTestId('legal-section-draft')).toBeNull()
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
