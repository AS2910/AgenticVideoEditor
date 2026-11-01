import type { LegalText } from './types'

/** Acceptable use policy, draft v3 (2026-10-31; v2 2026-10-24). The reporting and takedown steps are what
 *  app/safety_api.py and app/admin_api.py do: a public form, the admins told, share links
 *  revoked, accounts suspended, clones deleted. v3 (Voice consent V1 step 8) matches the line-check
 *  categories, bans robocalls and political content, and adds Lines we check and Grievance Officer:
 *  each changed section is marked `draft`, pending legal review. */
export const ACCEPTABLE_USE: LegalText = {
  title: 'Acceptable use policy',
  summary: 'What you may not make or do with Voltage, how to report misuse, and what we do about it.',
  sections: [
    {
      h: 'Why this matters',
      blocks: [
        'Voltage can make a person seem to say words they never said. That is useful for fixing a line in your own video, and harmful when it is used to fool people. This policy is part of the Terms of service and applies to everyone who uses Voltage, including people invited to a workspace.',
      ],
    },
    {
      // Voice consent V1 step 8: rewritten for the attestation flow; draft pending legal review.
      h: 'Consent comes first',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'Only use your own voice, or the voice of a person who has given you permission to change what they say. Owning the video, or having filmed it, is not permission.',
          'Tell Voltage the truth when it asks whose voice it is. Confirming that you have the rights and consent when you do not breaks this policy and may break the law.',
          'Use a voice cloned from a video only in that video, its variants and its language versions. Do not get round that, or round the check that proves a voice is yours before it is saved to My voices, for example by having someone else read the phrase or playing a recording.',
          'Never make someone appear to say something they would not agree to, even with their permission to use their voice.',
          'If a person withdraws their permission, stop using their voice and withdraw it in Voltage.',
        ],
        { counsel: 'Draft v3 (31 October 2026), pending legal review. Rewritten for Voice consent V1: the account holder\'s logged attestation for a voice used in its own video, own-voice proof for My voices. Decide whether a deceased person\'s voice may be used with the consent of their estate or legal heirs; the proposal is no, at least at launch.' },
      ],
    },
    {
      // Voice consent V1 step 8: matches the line-check category Impersonation; draft pending legal review.
      h: 'No impersonation',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'Do not clone or imitate the voice of a politician, celebrity or other public figure. Voltage refuses the voices and names it knows, and that list is not complete: the rule applies to everyone.',
          'Do not make a voice claim to be a named real person, an official, the police, a bank or a government body, or suggest that someone endorses something when they do not.',
          'Do not clone a child\'s voice.',
        ],
      ],
    },
    {
      h: 'No deception',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'Do not present a synthetic voice as a real recording where people would be misled, for example in news, evidence, testimony or a statement someone supposedly made.',
          'Do not make fake reviews, testimonials or endorsements.',
          'Do not remove, hide or alter the watermark, the provenance record or the details saying an export contains an AI-generated voice, or help anyone else to.',
        ],
      ],
    },
    {
      // Voice consent V1 step 8: political content is banned outright, as the line checks block it; draft pending legal review.
      h: 'Elections and public life',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'No political or election content in a synthetic voice: nothing that endorses or attacks a candidate or a party, and no instructions about voting. Voltage does not voice these lines.',
          'No content that misleads voters about candidates, parties, voting, or election results.',
          'No synthetic speech of candidates, election officials or political figures, whether or not you call it satire.',
        ],
        { counsel: 'Draft v3 (31 October 2026), pending legal review. The v2 draft allowed labelled political advertising; Voice consent V1 blocks political and election lines outright, which is simpler to enforce. Check the Election Commission of India advisories on deepfakes and synthetic content in campaigns, the Model Code of Conduct, and section 126 of the Representation of the People Act.' },
      ],
    },
    {
      // Voice consent V1 step 8: matches the line-check category Fraud and credentials, adds robocalls; draft pending legal review.
      h: 'No fraud',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'No scams, phishing, or calls and messages that pretend to be a relative, a bank, an employer or an official.',
          'No robocalls: do not use a Voltage voice in automated or mass phone calls or voice messages.',
          'No lines that ask for an OTP, a PIN, a password, card, UPI or bank details, or that press someone to transfer money now.',
          'Do not use a voice to get past voice checks at a bank or any other service.',
          'No financial fraud, market manipulation, or fake investment advice.',
        ],
      ],
    },
    {
      // Voice consent V1 step 8: matches the line-check categories Sexual and Hate, threats, harassment; draft pending legal review.
      h: 'No harm to others',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        [
          'No harassment, bullying, threats, or hate against anyone, including for their religion, caste, gender, sexuality, disability or origin.',
          'No sexual or explicit content in a synthetic voice, and never any sexual reference to a child. We report the second to the authorities.',
          'Nothing illegal, and nothing that the Information Technology Rules list as prohibited.',
        ],
        { counsel: 'Align this list with Rule 3(1)(b) of the IT (Intermediary Guidelines and Digital Media Ethics Code) Rules 2021 as amended, including the rules on synthetically generated information, and decide whether we are an intermediary for content shared by link. ' + 'Draft v3 (31 October 2026), pending legal review. The ban on sexual content is now total in a synthetic voice, as the line checks block it.' },
      ],
    },
    {
      // Voice consent V1 step 8: the line checks (app/safety/line_rules.py, line_checks.py) in plain words; draft pending legal review.
      h: 'Lines we check',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        'Voltage checks every line before it is voiced, in any voice, cloned or not. These lines are not voiced:',
        [
          'fraud: asking for an OTP, PIN, password, card, UPI or bank details, or pressing someone to transfer money now;',
          'impersonation: claiming to be a named real person, an official, the police, a bank or a government body;',
          'political and election content: endorsing or attacking a candidate or party, or instructions about voting;',
          'sexual or explicit content, and any sexual reference to a child, which we also report;',
          'hate, threats and harassment: slurs, threats of violence, and targeted harassment.',
        ],
        'Medical or financial claims, such as "cures diabetes" or "guaranteed returns", and lines our check is unsure about are held until a person on our team has looked, usually the same business day. A held line that is not cleared within 48 hours is turned down, and you are told why.',
        'Three blocked lines in 24 hours pause voicing with cloned voices on your account until our team has looked.',
        { counsel: 'Draft v3 (31 October 2026), pending legal review. Confirm the categories, the review turnaround (open decision 4) and the strike rule. The check reads the line with a language model (Anthropic, on the Sub-processors page); only lines that pass the rules reach it.' },
      ],
    },
    {
      h: 'Using the service fairly',
      blocks: [
        [
          'Do not try to break into accounts or Voltage itself, overload it, or get round its spending, rate or safety limits.',
          'Do not scrape, copy or resell the service, or share an account to dodge its checks.',
          'Do not upload anything you do not have the right to use.',
        ],
      ],
    },
    {
      h: 'Reporting misuse',
      blocks: [
        'Anyone can report misuse, with or without an account: use the form at the bottom of this page, or Report misuse on any shared link. Tell us where the content is (a link is best), what is wrong, and, if you want a reply, how to reach you.',
        'Each report is stored and our team is told straight away, in the app and by email. We read every report.',
        { counsel: 'Set the response promise. The IT Rules ask for complaints to be acknowledged within 24 hours and resolved within 15 days, and for content that impersonates a person or is artificially morphed to be removed within 24 hours of a complaint by that person. The form is rate limited to 5 reports an hour from one address.' },
      ],
    },
    {
      // Voice consent V1 step 8: voice actions added; draft pending legal review.
      h: 'What we do',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        'When something breaks this policy, depending on how serious it is, we may:',
        [
          'take down a shared link or a review link;',
          'suspend or delete a voice, including at the voice service;',
          'add a voice to the list of voices Voltage does not clone;',
          'refuse to clone a voice, or pause voice cloning and voicing with cloned voices for an account;',
          'suspend an account and the workspace it owns, which stops its work and its shared links at once;',
          'close an account;',
          'keep the evidence and report it to the authorities where the law requires or the harm is serious.',
        ],
        'Every action our team takes is recorded with a reason. If we act on your account we will tell you why, unless the law or someone\'s safety stops us, and you can write to us to ask us to look again.',
        { counsel: 'Confirm the appeal route and how long we keep reported content and evidence after a takedown. ' + 'Draft v3 (31 October 2026), pending legal review. Voice actions match the admin tools in RUNBOOK.md, Abuse and takedown.' },
      ],
    },
    {
      // Voice consent V1 step 8: the grievance officer for content complaints. Placeholders for the owner; draft pending legal review.
      h: 'Grievance Officer',
      draft: 'v3 2026-10-31, Voice consent V1',
      blocks: [
        'You can send a complaint about content made with Voltage, or about how we handled a report, to our Grievance Officer:',
        [
          'Name: [Grievance Officer name]',
          'Email: [Grievance Officer email]',
          'Phone: [Grievance Officer phone]',
          'Address: [Registered address]',
        ],
        'We will acknowledge your complaint within [24 hours] and resolve it within [15] days. A complaint from a person whose voice was used without consent, or who is shown as saying something they did not say, is acted on within [24 hours].',
        { counsel: 'Draft v3 (31 October 2026), pending legal review. The owner fills in a real officer and contact details (the same officer as the Privacy policy, unless counsel advises otherwise); nothing here is a real person yet. Confirm whether Voltage must appoint a Grievance Officer under Rule 3(2) of the IT Rules 2021 for content it makes and shares by link, the timelines, and whether a resident officer is needed.' },
      ],
    },
  ],
}
