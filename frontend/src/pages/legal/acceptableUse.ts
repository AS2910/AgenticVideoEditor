import type { LegalText } from './types'

/** Acceptable use policy (placeholder, G6). */
export const ACCEPTABLE_USE: LegalText = {
  title: 'Acceptable use policy',
  summary: 'What you may not make with Voltage.',
  sections: [
    { h: 'Consent comes first', blocks: ["Only clone a voice with the speaker's clear consent. Never make someone appear to say something they would not agree to."] },
    { h: 'No public figures', blocks: ['Do not clone or imitate the voices of politicians, celebrities or other public figures. Voltage refuses known ones.'] },
    { h: 'No deception or harm', blocks: ['No fraud, scams, election misinformation, harassment, hate, or content sexualising anyone without consent.'] },
    { h: 'Every export is marked', blocks: ['Exports carry an invisible watermark and a provenance record saying the voice was made by Voltage. Do not remove them.'] },
    { h: 'Reporting', blocks: ['Report misuse with the form below or from any shared link. We read every report.'] },
  ],
}
