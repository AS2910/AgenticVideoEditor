import type { LegalText } from './types'

/** Acceptable use policy, draft v2 (2026-10-24). The reporting and takedown steps are what
 *  app/safety_api.py and app/admin_api.py do: a public form, the admins told, share links
 *  revoked, accounts suspended, clones deleted. */
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
      h: 'Consent comes first',
      blocks: [
        [
          'Only clone the voice of a person who has given their own consent, through the check in Voltage, for that use. Your permission, a contract with them, or owning the video is not enough on its own.',
          'Do not get round the consent check, for example by having someone else read the sentence, playing a recording, or using a voice you made in another tool.',
          'Never make someone appear to say something they would not agree to, even with a clone they consented to.',
          'If a speaker withdraws consent, stop using their voice.',
        ],
        { counsel: 'Decide whether a deceased person\'s voice may be cloned with the consent of their estate or legal heirs; the proposal is no, at least at launch.' },
      ],
    },
    {
      h: 'No impersonation',
      blocks: [
        [
          'Do not clone or imitate the voice of a politician, celebrity or other public figure. Voltage refuses the names it knows, and that list is not complete: the rule applies to everyone.',
          'Do not pretend to be another person or organisation, or suggest that someone endorses something when they do not.',
          'Do not clone a child\'s voice.',
        ],
      ],
    },
    {
      h: 'No deception',
      blocks: [
        [
          'Do not present a synthetic voice as a real recording where people would be misled, for example in news, evidence, testimony or a statement someone supposedly made.',
          'Do not make fake reviews, testimonials or endorsements.',
          'Do not remove, hide or alter the watermark or the provenance record on an export, or help anyone else to.',
        ],
      ],
    },
    {
      h: 'Elections and public life',
      blocks: [
        [
          'No content that misleads voters about candidates, parties, voting, or election results.',
          'No synthetic speech of candidates, election officials or political figures, whether or not you call it satire.',
          'No political advertising made with a synthetic voice unless it says clearly that the voice is synthetic and the law allows it.',
        ],
        { counsel: 'Check the Election Commission of India advisories on deepfakes and synthetic content in campaigns, the Model Code of Conduct, and section 126 of the Representation of the People Act. Decide whether political advertising should be banned outright, which is simpler to enforce.' },
      ],
    },
    {
      h: 'No fraud',
      blocks: [
        [
          'No scams, phishing, or calls and messages that pretend to be a relative, a bank, an employer or an official.',
          'Do not use a voice to get past voice checks at a bank or any other service.',
          'No financial fraud, market manipulation, or fake investment advice.',
        ],
      ],
    },
    {
      h: 'No harm to others',
      blocks: [
        [
          'No harassment, bullying, threats, or hate against anyone, including for their religion, caste, gender, sexuality, disability or origin.',
          'No sexual content made with a real person\'s voice without their consent, and never any sexual content involving a child.',
          'Nothing illegal, and nothing that the Information Technology Rules list as prohibited.',
        ],
        { counsel: 'Align this list with Rule 3(1)(b) of the IT (Intermediary Guidelines and Digital Media Ethics Code) Rules 2021 as amended, including the rules on synthetically generated information, and decide whether we are an intermediary for content shared by link.' },
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
      h: 'What we do',
      blocks: [
        'When something breaks this policy, depending on how serious it is, we may:',
        [
          'take down a shared link;',
          'delete a voice clone at the voice service;',
          'refuse to clone a voice, or close voice cloning for an account;',
          'suspend an account and the workspace it owns, which stops its work and its shared links at once;',
          'close an account;',
          'keep the evidence and report it to the authorities where the law requires or the harm is serious.',
        ],
        'Every action our team takes is recorded with a reason. If we act on your account we will tell you why, unless the law or someone\'s safety stops us, and you can write to us to ask us to look again.',
        { counsel: 'Confirm the appeal route and how long we keep reported content and evidence after a takedown.' },
      ],
    },
  ],
}
