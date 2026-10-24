import type { LegalText } from './types'
import { VENDORS } from './subprocessors'

/** Privacy policy, draft v2 (2026-10-24), written against India's Digital Personal Data
 *  Protection Act 2023. What it says Voltage keeps, deletes and exports is read from the code:
 *  app/dataexport.py, app/purge.py, delete_account in app/api/main.py, app/safety_api.py. */
export const PRIVACY: LegalText = {
  title: 'Privacy policy',
  summary: 'What personal data Voltage keeps, why, who else receives it, how long we keep it, and your rights over it.',
  sections: [
    {
      h: 'Who we are',
      blocks: [
        '[Company legal name], [Registered address], runs Voltage. For your personal data we are the "Data Fiduciary" under India\'s Digital Personal Data Protection Act 2023 (the DPDP Act): we decide why and how it is used.',
        'When you upload a video of other people, you decide what is done with their voices and faces in it. You must have their permission, and for a cloned voice, their own consent (see Voices and consent below).',
        { counsel: 'Confirm the fiduciary and processor roles, especially for videos of third parties uploaded by a user, and for business customers who may want a data processing agreement with us. Check whether we could be notified as a Significant Data Fiduciary (voice data at scale), which would add a Data Protection Officer, audits and impact assessments.' },
      ],
    },
    {
      h: 'What we collect',
      blocks: [
        [
          'Your account: email address, a scrambled (scrypt) form of your password, or your name, email and profile picture link from Google if you sign in with Google; the version of the Terms you accepted and when.',
          'Your work: the videos you upload or import, their audio, transcripts, still frames Voltage looks at, your project briefs and reference files, your messages to Voltage, the lines and takes it makes, your exports, review comments and share links.',
          'Voices: samples of a speaker\'s voice cut from your video, the cloned or designed voices made from them, and the descriptions of voices you design.',
          'Consent records: see the next section.',
          'Billing: your country, and if you add them, your business\'s legal name, GSTIN and state; your plan, credits, purchases, invoices and refunds. Card and bank details stay with the payment provider.',
          'Usage: what each paid step cost, and the steps you take in the app (for example "video uploaded" or "export made"), kept in our own database. Help explains this under What Voltage counts.',
          'Workspaces: the people you invite, their roles and email addresses.',
          'Messages to us: feedback, support requests, and abuse reports (where, what kind, the details, and a contact address if the reporter gives one).',
          'Technical data: error reports, and our web server logs, which hold IP addresses and the pages requested.',
        ],
        { counsel: 'Web server and container logs rotate by size (5 files of 20 MB) and are not otherwise cleared; propose a fixed period such as [30] days. IP addresses are used in memory to rate limit the abuse form and are not stored with a report.' },
      ],
    },
    {
      h: 'Voices and consent',
      blocks: [
        'A voice is cloned only with the speaker\'s own consent. First, you confirm in Voltage that you have the speaker\'s permission. Then the speaker reads aloud a sentence shown on screen, which ends with a random four-digit code so an old recording cannot be reused. We record it and check it: that the right words were said, and that the voice matches the speaker in the video (a similarity score). If the result is borderline, a person on our team reviews it before any clone is made. If it fails, nothing is cloned.',
        'For each consent we keep a consent record:',
        [
          'the sentence shown on screen, including its code;',
          'the recording of the speaker reading it;',
          'the result of the check, its reason, and its scores (such as the speech match and the voice similarity score);',
          'the name and version of the checking service and models used;',
          'if a person reviewed it, who did and what they decided;',
          'the speaker and video it is for, the account that asked, and the times the check started, finished and consent was given.',
        ],
        'Consent can be withdrawn at any time from the video. The clone is deleted at the voice service straight away and nothing new is made with it. Work already exported is not changed.',
        { counsel: 'What the code stores today: the sentence and code, the recording, pass or fail with a reason, the provider name, the speaker label, the video, the account, and the start, check and consent times. The check itself is a test-mode placeholder, so there are no scores, model versions or admin reviews yet, and voice cloning is closed to the public until it is real. Publish the list above only once those fields are stored, or trim it to what ships.' },
      ],
    },
    {
      h: 'How long we keep consent records',
      blocks: [
        'We keep a consent record for 7 years after the voice or video it covers is deleted, so we can show that a voice was cloned with permission if that is ever questioned. Then it is cleared.',
        { counsel: 'Proposed period: 7 years after deletion (AVE_CONSENT_RETENTION_YEARS, default 7). Please confirm against the limitation periods for claims about a voice (Limitation Act 1963, personality and privacy claims) and the DPDP Act\'s rule to erase data once its purpose is served. Also note two gaps for engineering: the consent recordings and check results are not cleared when the 7 years end (only the summary record is), and deleting an account keeps the consent recordings but not the consent time of the videos it removes.' },
      ],
    },
    {
      h: 'Why we use your data',
      blocks: [
        [
          'To run Voltage for you: transcribe, plan, voice and render your videos.',
          'To make sure voices are cloned only with consent, and to handle misuse reports.',
          'To bill you, issue GST invoices and keep tax records.',
          'To keep Voltage safe and working: spending limits, rate limits, error reports and backups.',
          'To improve Voltage, using counts of the steps people take, not the content of your videos.',
          'To meet the law, and answer lawful requests from authorities.',
        ],
        'We rely on your consent, given when you create your account, and on the "legitimate uses" the DPDP Act allows, such as meeting a legal duty.',
        { counsel: 'Map each purpose to consent (section 6) or a legitimate use (section 7). A DPDP consent notice must be itemised and available in English or any Eighth Schedule language on request; decide whether sign-up needs a separate notice from this policy, and whether marketing email needs its own opt-in.' },
      ],
    },
    {
      h: 'Who receives your data',
      blocks: [
        'The services that do the work, listed below, each receiving only what it needs. People you invite to your workspace, and anyone you send a share link to, can see what you share with them. We may also disclose data when the law requires it, or to a buyer of the business, who would be bound by this policy.',
        'We do not sell your data and we do not use it for advertising.',
        { vendors: VENDORS },
        { before: 'The same list, with how we choose services, is on the', link: 'Sub-processors page', href: '#subprocessors' },
      ],
    },
    {
      h: 'Data outside India',
      blocks: [
        'Several of these services are in the United States, so your data is processed there.',
        { counsel: 'Section 16 of the DPDP Act lets data go abroad except to countries the government restricts. Confirm none of the vendor countries is restricted at launch, and whether any sector rule applies. Decide where the server is hosted.' },
      ],
    },
    {
      h: 'How long we keep the rest',
      blocks: [
        [
          'Deleted videos, projects and voices go to the Bin for 30 days, then are removed for good: their media, transcripts, takes, exports and comments, and their voice clones at the voice service. What their paid steps cost stays in Usage, by name only.',
          'When you delete your account, everything above goes at once, with your voices (at the voice service too), samples, defaults, templates, pins and your sign-in. You leave any workspace you joined; another person\'s work there stays theirs.',
          'What we keep after that: consent records (see above), invoices and payment records for as long as tax law requires, and a note that you asked for the deletion and when.',
          'Share links expire after 30 days unless you chose otherwise, and at most after a year. Invitations expire after 14 days.',
          'Backups are kept for 14 days, so deleted data leaves them within 14 days.',
        ],
        { counsel: 'Confirm the invoice retention period (the CGST Act asks for records to be kept 72 months from the annual return due date). The code also keeps, after account deletion, the counted steps, error reports, abuse reports and the data-export zips, with no expiry. Propose: usage counts anonymised after [24] months, error reports deleted after [90] days, export zips deleted after [7] days. These need code changes before launch.' },
      ],
    },
    {
      h: 'Your rights',
      blocks: [
        'Under the DPDP Act you have these rights. Most you can use yourself in Voltage; for the rest, write to our Grievance Officer.',
        [
          'Access: download all your data from Settings, Your data, as a zip. It holds your records as JSON files, one for each kind (videos, projects, transcripts, takes, messages, billing, consent records, the steps counted and more), and a list of every stored media file, which you can download from Voltage while your account exists.',
          'Correction: change your details and your work in the app, or write to us to correct anything you cannot change yourself.',
          'Erasure: delete a video, project or voice (it goes to the Bin, then for good after 30 days), or delete your whole account from Settings. We keep only what the section above lists.',
          'Withdraw consent: withdraw a speaker\'s consent from the video at any time, or withdraw consent to everything by deleting your account. Withdrawing does not undo what was lawfully done before.',
          'Nominate someone: you can name a person to use these rights for you if you die or cannot act. Write to the Grievance Officer with their name and contact details.',
          'Complain: write to the Grievance Officer. If you are not satisfied with the answer, you can complain to the Data Protection Board of India.',
        ],
        { counsel: 'There is no in-app nominee feature; it is handled by email. Confirm the response time to promise for each right under the DPDP Rules 2025, and whether the export needs to include the media files themselves rather than a list. Decide whether the speaker in a video (who is not our user) can use these rights directly, for example to ask for their consent record or to have their clone deleted, and how we verify who they are.' },
      ],
    },
    {
      h: 'Grievance Officer',
      blocks: [
        'Name: [Grievance Officer name]',
        'Email: [Grievance Officer email]',
        'Address: [Registered address]',
        'We will acknowledge your message within [48 hours] and answer within [30] days.',
        { counsel: 'Name a real officer and contact details before publishing; the IT Rules 2021 and the DPDP Act both require these to be published. Confirm the timelines.' },
      ],
    },
    {
      h: 'Children',
      blocks: [
        'Voltage is for adults. We do not knowingly collect data from anyone under 18. If you think a child has an account, write to us and we will delete it.',
        'Videos uploaded by adults may still show children. Do not clone a child\'s voice.',
        { counsel: 'Under the DPDP Act, processing a child\'s data needs verifiable parental consent, and tracking or targeted advertising aimed at children is not allowed. Decide whether a child\'s voice may ever be cloned with a parent\'s consent; the proposal here is never.' },
      ],
    },
    {
      h: 'Keeping your data safe',
      blocks: [
        'Voltage runs over HTTPS. Passwords are stored only in scrambled form. Downloads use signed links that expire. Each workspace sees only its own work. Error reports have passwords, keys and tokens removed before they leave the server.',
        'If a breach affects your personal data, we will tell you and the Data Protection Board of India as the law requires.',
        { counsel: 'Confirm the breach notification wording and timeline under the DPDP Rules 2025, and the CERT-In 6-hour reporting direction.' },
      ],
    },
    {
      h: 'Cookies and local storage',
      blocks: [
        'Voltage uses a sign-in cookie to keep you signed in, and stores small preferences in your browser, such as light or dark mode. It does not use advertising or third-party tracking cookies.',
      ],
    },
    {
      h: 'Changes to this policy',
      blocks: [
        'If we change this policy in a way that matters, we will tell you by email or in the app before the change takes effect.',
      ],
    },
  ],
}
