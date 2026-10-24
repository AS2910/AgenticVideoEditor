import type { LegalText } from './types'

/** Terms of service, draft v2 (2026-10-24). Describes what the code does today; the For counsel
 *  notes are the points a lawyer has to decide or confirm before this is published. */
export const TERMS: LegalText = {
  title: 'Terms of service',
  summary: 'The agreement between you and us when you use Voltage: what you may do, what you pay, what we promise and what we do not.',
  sections: [
    {
      h: 'Who we are',
      blocks: [
        'Voltage is run by [Company legal name], a company registered in India with Corporate Identification Number [CIN], whose registered office is at [Registered address]. In these terms "we" and "us" means that company, and "you" means the person or business using Voltage.',
        'You can write to us at [Contact email]. Questions about your personal data go to our Grievance Officer, named in the Privacy policy.',
        { counsel: 'Fill in the legal entity, CIN, registered address and contact address. Confirm whether the contracting entity differs for customers outside India.' },
      ],
    },
    {
      h: 'These terms',
      blocks: [
        'By creating an account, or by continuing with Google, you agree to these terms, the Privacy policy and the Acceptable use policy. If you use Voltage for a business, you agree on its behalf and confirm you are allowed to.',
        'When you create an account we record which version of these terms you accepted and when.',
        { counsel: 'The app records a version string at sign-up (AVE_TERMS_VERSION, now "draft-2026-10-22"). Decide how a new version is accepted by existing users: notice by email and continued use, or a fresh click to accept. Consider whether clickwrap at sign-up is enough under the Indian Contract Act and the IT Act for this service.' },
      ],
    },
    {
      h: 'What Voltage does',
      blocks: [
        'Voltage edits what people say in videos. It transcribes the speech, suggests changes, and makes new lines in a synthetic voice: a voice cloned from the speaker, with their consent, or a voice from a catalogue or designed from a description. Every change is shown to you as a proposal first, and nothing goes into your video until you add it.',
        'Voltage uses outside services to do this work, such as speech recognition, language models and voice synthesis.',
        { before: 'Each one, and what it receives, is listed on the', link: 'Sub-processors page', href: '#subprocessors' },
      ],
    },
    {
      h: 'Who can use Voltage',
      blocks: [
        'You must be at least 18 years old and able to make a binding contract. Voltage is not meant for children and we do not knowingly let anyone under 18 create an account.',
        { counsel: 'The app does not check age today. Under the DPDP Act a "child" is anyone under 18, and processing their data needs verifiable consent from a parent. Proposal: adults only, stated here and at sign-up, with an account closed if we learn it belongs to a child. Confirm whether a self-declared age at sign-up is enough.' },
      ],
    },
    {
      h: 'Your account and workspace',
      blocks: [
        'Keep your password and sign-in links to yourself. You are responsible for what is done in your account.',
        'You can invite people to your workspace as Editors or Reviewers. You are responsible for what they do there, and for having the right to share your videos with them. An invitation lasts 14 days. You can also share a video or an export by link; anyone with the link can open it until it expires (30 days unless you choose otherwise, at most a year) or you turn it off.',
      ],
    },
    {
      h: 'Voices and consent',
      blocks: [
        'You may only clone the voice of a person who has given their own consent. Your permission is not enough on its own: the speaker must agree, and before a voice is cloned they read a sentence shown on screen aloud, which we record and check. The Privacy policy says what is kept from that check and for how long.',
        'We may refuse to clone a voice, for example when the check does not pass, when the voice seems to belong to a public figure, or when a person on our team reviewing a borderline case is not satisfied. We may delete a clone, and suspend an account, if we learn consent was not given.',
        'A speaker, or you on their behalf, can withdraw consent at any time. When consent is withdrawn the clone is deleted at the voice service straight away and no new lines are made with it.',
        { counsel: 'Voice cloning is closed to the public today and turned on per person by an admin, because the consent check runs in test mode (it keeps the recording but does not yet check the words or the voice). The speaker similarity check and admin review of borderline cases described here are planned for launch. Publish this wording only once they are live, or reword to match what ships. Consider whether the speaker should also accept a short consent statement of their own, separate from these terms.' },
      ],
    },
    {
      h: 'Your content',
      blocks: [
        'You keep every right you have in the videos, audio, words and files you upload, and in what Voltage makes from them. You confirm you have the right to upload and edit them, including the rights of everyone who appears or is heard in them.',
        'You give us a licence to store, copy, process and transmit your content, and to send it to the services on the Sub-processors page, only to run Voltage for you, to keep it safe, and to meet the law. The licence ends when your content is deleted, except for what we must keep, such as consent records and invoices.',
        'We do not use your content to train our own models.',
        { counsel: 'Confirm the licence scope. Check each vendor\'s current API terms on retention and training (the code sends data through their APIs, not their consumer apps) before stating anything about them here. Decide whether we want any right to use anonymised usage numbers to improve the product.' },
      ],
    },
    {
      h: 'What Voltage makes',
      blocks: [
        'Lines in a synthetic voice are made by a machine. Every export carries a hidden watermark and a provenance record saying that the voice was made with Voltage. You must not remove or alter them, and you must not present a synthetic voice as a real recording where that would mislead people.',
        'Suggestions from Voltage can be wrong. You decide what goes into your video and you are responsible for what you publish.',
        { counsel: 'The watermark and provenance signature run in test mode today (a metadata mark and a test signature). Consider labelling duties for synthetic media under the IT Rules and any advisories in force at launch, and in the markets where users publish.' },
      ],
    },
    {
      h: 'Credits',
      blocks: [
        'Paid steps in Voltage, such as making a voice line, transcribing or planning an edit, use credits. The Billing page shows what you have left and what each step costs before you commit to it. When your credits run out, paid steps stop until you add more; free steps keep working.',
        [
          'A new account starts with free trial credits. They do not lapse.',
          'A plan gives you a set number of credits each calendar month. Credits you do not use lapse when that month ends.',
          'A top-up gives you extra credits. They lapse 12 months after you buy them.',
          'Credits we give you, for example as a goodwill gesture, do not lapse.',
          'Credits are used soonest-to-lapse first.',
        ],
        'Credits are a way to pay for work in Voltage. They have no cash value, cannot be transferred or sold, and are not refunded when they lapse or when you delete your account.',
        { counsel: 'Prices and credit amounts are placeholders in the code (backend/app/billing/prices.py) until the business signs them off; this page deliberately names none. Check that lapsing credits and "no cash value" are acceptable under the Consumer Protection Act 2019 and the E-Commerce Rules, and whether credits could be treated as a prepaid payment instrument under RBI rules (they are only usable on Voltage, which should keep them closed-system).' },
      ],
    },
    {
      h: 'Plans, payment and GST',
      blocks: [
        'Prices are shown on the Billing page in US dollars or Indian rupees before you pay. Payments are taken by Stripe or Razorpay on their own checkout pages. We do not see or store your card or bank details.',
        'Prices for customers in India include GST at 18%: CGST and SGST when you are in the same state as us, or IGST when you are in another state. Add your GSTIN in Billing to get a tax invoice in your business\'s name. For customers outside India the service is an export of services and no GST is charged. Every payment gets an invoice, which you can open from Billing.',
        'Today a plan is bought with a single payment at checkout, and its credits are added at the start of each month while the plan is on your account.',
        { counsel: 'The code takes one-off payments (Stripe Checkout in payment mode, Razorpay orders); there is no recurring charge and no self-serve cancel yet. Before launch, decide the plan model (monthly subscription with auto-renewal, or a one-month pass) and write renewal, cancellation and notice terms to match, including the RBI e-mandate rules for recurring card payments in India. Confirm the GST position (SAC 998314, place of supply, zero-rating for exports under a letter of undertaking, and whether OIDAR rules apply to customers abroad). Seller name, GSTIN and state come from AVE_SELLER_NAME, AVE_SELLER_GSTIN and AVE_SELLER_STATE.' },
      ],
    },
    {
      h: 'Refunds',
      blocks: [
        'If something went wrong with a payment, write to us. Our team can refund a payment in full through the provider that took it. A refund takes back the credits that payment gave you, and ends the plan it started. Each payment can be refunded once.',
        'We do not refund credits you have already used, or credits that have lapsed, unless the law says we must.',
        { counsel: 'Refunds are admin-only and in full today (no partial refunds). Propose a refund window, for example [14] days from payment for unused credits, and say how a refund works when some of the credits are already spent (the code takes back the full amount, which can leave a negative balance owed from later credits). Check against consumer law.' },
      ],
    },
    {
      h: 'Using Voltage fairly',
      blocks: [
        'You must follow the Acceptable use policy. In short: only real consent, no impersonation, no deception, no fraud, no election manipulation, and no harm to others.',
        { before: 'Read the full', link: 'Acceptable use policy', href: '#acceptable-use' },
      ],
    },
    {
      h: 'Suspending or closing an account',
      blocks: [
        'We may suspend or close an account that breaks these terms or the Acceptable use policy, puts others at risk, or where the law requires it. We will tell you why unless the law or a safety reason stops us. Where it is fair to, we will give you a chance to fix the problem first.',
        'You can delete your account at any time from Settings. The Privacy policy explains what is deleted and what we must keep.',
        { counsel: 'Decide whether unused paid credits are refunded when we close an account without fault on the user\'s side, and set the notice period for closing an account for convenience.' },
      ],
    },
    {
      h: 'Changes and availability',
      blocks: [
        'Voltage is a new service. Features may change, and we may pause paid work for a while to protect the service, in which case nothing is charged while it is paused. We try to keep Voltage running but do not promise it will always be available or free of errors.',
        'Some features are in beta. They may change or be removed, and we will say so in the app.',
      ],
    },
    {
      h: 'Our responsibility to you',
      blocks: [
        'Voltage is provided "as is". To the extent the law allows, we do not give any promise that it will suit a particular purpose, that its suggestions are accurate, or that it will be uninterrupted.',
        'To the extent the law allows, we are not responsible for indirect or consequential loss, such as lost profits, revenue, data or goodwill. Our total responsibility to you for any claim is limited to the amount you paid us in the 12 months before the claim, or [INR amount] if that is more.',
        'Nothing here limits responsibility that cannot be limited by law, such as for fraud.',
        { counsel: 'Set the liability cap and confirm the exclusions are enforceable for consumers under the Consumer Protection Act 2019 and section 23 of the Indian Contract Act. Decide whether business customers get different terms.' },
      ],
    },
    {
      h: 'Your responsibility to us',
      blocks: [
        'If someone makes a claim against us because of content you uploaded or made, a voice you cloned without real consent, or your breach of these terms, you agree to cover our reasonable losses and costs from that claim.',
        { counsel: 'Confirm the scope of this indemnity, especially for consumers.' },
      ],
    },
    {
      h: 'Law and disputes',
      blocks: [
        'These terms are governed by the laws of [India]. Courts in [City] have exclusive jurisdiction, unless the law gives you the right to bring a claim where you live.',
        'Before going to court, please write to us so we can try to resolve the problem.',
        { counsel: 'Choose the governing law and seat. Consider arbitration under the Arbitration and Conciliation Act 1996 for business customers, and what applies to customers outside India.' },
      ],
    },
    {
      h: 'Changes to these terms',
      blocks: [
        'We may update these terms. If a change matters, we will tell you by email or in the app at least [30] days before it takes effect. If you do not agree, you can delete your account before then.',
        { counsel: 'Confirm the notice period.' },
      ],
    },
  ],
}
