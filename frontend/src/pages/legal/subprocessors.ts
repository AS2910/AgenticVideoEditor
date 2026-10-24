import type { LegalText, Vendor } from './types'

/** Every outside service the code sends data to, read from backend/app/adapters, app/billing,
 *  app/auth.py, app/errors_report.py, app/linkimport.py, app/config.py and DEPLOY.md (2026-10-24).
 *  A vendor added to the code belongs here too. */
export const VENDORS: Vendor[] = [
  {
    name: 'Anthropic (Claude)',
    does: 'The language model behind Voltage: it reads your request, plans edits, checks wording and writes Voltage\'s replies.',
    gets: 'The transcript of your video, your messages to Voltage, your project brief and the text of reference files you add, the lines being edited, and a few still frames from your video when Voltage looks at what is on screen.',
    why: 'To understand your video and your request and suggest changes.',
    when: 'Every time you ask Voltage for something, and when a video is first read.',
    where: 'United States',
  },
  {
    name: 'OpenAI (Whisper)',
    does: 'Speech recognition.',
    gets: 'The audio track of your video.',
    why: 'To turn speech into a transcript with the time of every word.',
    when: 'When a video is uploaded or its speech is read again.',
    where: 'United States',
  },
  {
    name: 'ElevenLabs',
    does: 'Synthetic voices: cloning, designing voices from a description, and speaking lines.',
    gets: 'Short samples of a speaker\'s voice cut from your video (only after consent), the text of the lines to speak, finished lines to pass through a speaker\'s clone so they sound like that speaker, and the description of a voice you design. A cloned voice is stored at ElevenLabs until it is deleted.',
    why: 'To make the new lines in a voice that matches.',
    when: 'When a voice is cloned or designed, and every time a line is voiced. When a voice, a video or your account is deleted for good, its clones are deleted there too.',
    where: 'United States',
  },
  {
    name: 'Stripe',
    does: 'Card payments and refunds.',
    gets: 'The amount, currency and description of a purchase, a purchase reference and your account reference. You type your card details into Stripe\'s own page; they never reach us.',
    why: 'To take payment.',
    when: 'Only when you buy a plan or top-up and Stripe is the payment provider.',
    where: '[Region of the Stripe account]',
  },
  {
    name: 'Razorpay',
    does: 'Payments in India (cards, UPI, net banking) and refunds.',
    gets: 'The amount, currency and description of a purchase, a purchase reference and your account reference, and what you enter in Razorpay\'s checkout.',
    why: 'To take payment.',
    when: 'Only when you buy a plan or top-up and Razorpay is the payment provider.',
    where: 'India',
  },
  {
    name: 'Resend',
    does: 'Sends Voltage\'s emails.',
    gets: 'Your email address and the email itself: sign-in and verification links, password resets, invitations, review digests, receipts and invoices, spend alerts, and the confirmation that an account was deleted. Abuse reports go to our own safety inbox through it.',
    why: 'To send you the emails the service needs.',
    when: 'Whenever Voltage emails you.',
    where: 'United States',
  },
  {
    name: 'Sentry',
    does: 'Error reports.',
    gets: 'The error message, where in the code it happened, the technical trace and your account id. Passwords, keys and tokens are removed before it is sent.',
    why: 'To find and fix what breaks.',
    when: 'Only when an error happens, and only if error reporting is switched on.',
    where: '[Region of the Sentry project]',
  },
  {
    name: 'Google sign-in',
    does: 'Lets you sign in with your Google account.',
    gets: 'Google tells us your name, email address and profile picture link (the "openid email profile" scopes). Google learns that you signed in to Voltage.',
    why: 'To create and sign in to your account.',
    when: 'Only if you choose Continue with Google.',
    where: 'United States',
  },
  {
    name: '[Hosting provider]',
    does: 'The server Voltage runs on: the app, its database and every stored file.',
    gets: 'Everything Voltage stores, on the server\'s own disk: your account, videos and media, voices, consent records, billing records and logs.',
    why: 'To run the service.',
    when: 'Always.',
    where: '[Data centre region]',
  },
  {
    name: '[Backup storage provider]',
    does: 'Keeps the nightly backups off the main server.',
    gets: 'A copy of the database and stored files, kept for 14 days.',
    why: 'To restore the service after a failure.',
    when: 'Every night.',
    where: '[Backup region]',
  },
]

export const SUBPROCESSORS: LegalText = {
  title: 'Sub-processors',
  summary: 'The outside services Voltage uses to do its work, what each one receives, and why.',
  sections: [
    {
      h: 'How we choose them',
      blocks: [
        'Voltage sends your data only to the services below, only what each one needs, and only to do the work you asked for. We do not sell your data and we do not share it for advertising.',
        'This list comes from the code: each service Voltage talks to is here. If we add one, we will update this page and tell you by email or in the app at least [30] days before it receives your data.',
        { counsel: 'Confirm the notice period for new sub-processors. Put a data processing agreement in place with each vendor (several offer standard terms) and check each one\'s retention and training terms for API data. Fill in the hosting, backup, Stripe and Sentry regions once the accounts exist.' },
      ],
    },
    { h: 'The services', blocks: [{ vendors: VENDORS }] },
    {
      h: 'Links you import from',
      blocks: [
        'When you paste a public Google Drive or Dropbox link to import a video, our server fetches the file from Google or Dropbox. They see a request from our server for that file. They are services you choose to use, not services we send your data to.',
        'Our HTTPS certificates come from Let\'s Encrypt, which learns our domain name and nothing about you.',
      ],
    },
    {
      h: 'What we do not use',
      blocks: [
        [
          'No outside analytics or advertising trackers. The steps Voltage counts are kept in our own database.',
          'No lip-sync service, and no outside object storage: media is kept on our own server.',
          'Separating speech from background sound runs on our own server.',
        ],
      ],
    },
  ],
}
