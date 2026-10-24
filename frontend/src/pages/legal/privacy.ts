import type { LegalText } from './types'

/** Privacy policy (placeholder, G6). */
export const PRIVACY: LegalText = {
  title: 'Privacy policy',
  summary: 'What Voltage keeps about you, and what you can do about it.',
  sections: [
    { h: 'What we keep', blocks: ['Your account, your videos and what Voltage makes from them, your voices, consent records, usage and spend, and the steps you take in the app (see What Voltage counts in Help).'] },
    { h: 'Voices and consent', blocks: ["A speaker's voice is cloned only with consent, after they read a sentence aloud. Withdrawing consent deletes the clone at the voice service at once. Consent records are kept for 7 years after a voice or video is deleted, unless the law asks for a different period."] },
    { h: 'Who else sees it', blocks: ['The voice, transcription and language services that do the work, under their own terms, and nobody else. We do not sell your data.'] },
    { h: 'Your rights', blocks: ['Download everything from Settings at any time, and delete your account and data from Settings. Write to us to correct anything.'] },
  ],
}
