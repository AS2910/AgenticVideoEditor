import { Wordmark } from '../components/Wordmark'
import { hrefFor } from '../lib/route'
import { useEffect } from 'react'
import { AbuseReport } from '../components/AbuseReport'
import { track } from '../lib/analytics'

/** G6: Terms, Privacy and Acceptable Use. Placeholder text, clearly marked as a draft that
 *  needs legal review (SETUP_NEEDED.md). Public: no account needed to read them. */
export type LegalDoc = 'terms' | 'privacy' | 'acceptable-use'

const DOCS: Record<LegalDoc, { title: string; sections: [string, string][] }> = {
  terms: {
    title: 'Terms of service',
    sections: [
      ['Using Voltage', 'Voltage edits what people say in your videos with synthetic voices. You may use it for videos you have the right to edit, with the consent of everyone whose voice is cloned.'],
      ['Your account', 'Keep your sign-in to yourself. You are responsible for what is made in your account and by the people you invite to your workspace.'],
      ['Credits and payment', 'Paid steps use credits. Plans renew monthly until cancelled. Prices, taxes and refunds will be set out here before payments are taken.'],
      ['What you make', 'You own your videos and what Voltage makes from them. We need a licence to store and process them to run the service, and nothing more.'],
      ['When we may stop', 'We may suspend an account that breaks the Acceptable use policy, and will say why.'],
    ],
  },
  privacy: {
    title: 'Privacy policy',
    sections: [
      ['What we keep', 'Your account, your videos and what Voltage makes from them, your voices, consent records, usage and spend, and the steps you take in the app (see What Voltage counts in Help).'],
      ['Voices and consent', 'A speaker\'s voice is cloned only with consent, after they read a sentence aloud. Withdrawing consent deletes the clone at the voice service at once. Consent records are kept for 7 years after a voice or video is deleted, unless the law asks for a different period.'],
      ['Who else sees it', 'The voice, transcription and language services that do the work, under their own terms, and nobody else. We do not sell your data.'],
      ['Your rights', 'Download everything from Settings at any time, and delete your account and data from Settings. Write to us to correct anything.'],
    ],
  },
  'acceptable-use': {
    title: 'Acceptable use policy',
    sections: [
      ['Consent comes first', 'Only clone a voice with the speaker\'s clear consent. Never make someone appear to say something they would not agree to.'],
      ['No public figures', 'Do not clone or imitate the voices of politicians, celebrities or other public figures. Voltage refuses known ones.'],
      ['No deception or harm', 'No fraud, scams, election misinformation, harassment, hate, or content sexualising anyone without consent.'],
      ['Every export is marked', 'Exports carry an invisible watermark and a provenance record saying the voice was made by Voltage. Do not remove them.'],
      ['Reporting', 'Report misuse with the form below or from any shared link. We read every report.'],
    ],
  },
}

export function LegalPage({ doc }: { doc: LegalDoc }) {
  const d = DOCS[doc]
  useEffect(() => { track('legal.opened', { doc }) }, [doc])
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="flex h-[62px] items-center gap-4 border-b-[1.5px] border-foreground bg-card px-4 sm:px-6"><a href={hrefFor({ page: 'projects' })} className="no-underline"><Wordmark /></a></header>
      <main className="mx-auto flex w-full max-w-[760px] flex-col gap-6 px-4 pt-10 pb-20 sm:px-6" data-testid="legal-page">
        <div className="flex flex-col gap-3">
          <span className="stamp need self-start" data-testid="legal-draft">Draft, needs legal review</span>
          <h1 className="disp m-0 text-[40px] leading-tight font-bold">{d.title}</h1>
          <p className="m-0 text-muted-foreground">This is placeholder text written to describe how Voltage works. It is not legal advice and has not been reviewed by a lawyer yet.</p>
        </div>
        {d.sections.map(([h, t]) => (
          <section key={h} className="flex flex-col gap-1.5"><h2 className="disp m-0 text-[22px] font-bold">{h}</h2><p className="m-0">{t}</p></section>
        ))}
        <nav aria-label="Policies" className="flex flex-wrap gap-4 border-t border-line pt-4 text-sm">
          <a href="#terms">Terms of service</a><a href="#privacy">Privacy policy</a><a href="#acceptable-use">Acceptable use policy</a>
        </nav>
        {doc === 'acceptable-use' && <AbuseReport />}
      </main>
    </div>
  )
}

/** The three policy links, for footers. */
export function LegalLinks({ className = '' }: { className?: string }) {
  return (
    <nav aria-label="Policies" className={`flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground ${className}`}>
      <a className="text-muted-foreground" href="#terms">Terms</a><a className="text-muted-foreground" href="#privacy">Privacy</a><a className="text-muted-foreground" href="#acceptable-use">Acceptable use</a>
    </nav>
  )
}
