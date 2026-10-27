import { useCallback, useEffect, useId, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, getPricing, joinWaitlist } from '../api'
import type { PublicPricing } from '../api'
import { Wordmark } from '../components/Wordmark'
import { LegalLinks } from './LegalPage'
import { said } from './fmt'

/** Launch item 8: the public landing page, for people who are not signed in (`#`, `#home`;
 *  `#welcome` shows it to anyone). Run 5 item 9: it leads with ad teams and agencies (change
 *  every ad at once, three steps across a campaign); editing one video, with the sample ad
 *  before and after, is the second section. Then what Voltage does, prices read from the server (`GET /pricing`, built from app/billing/prices.py), the
 *  FAQ, and Request access while Voltage is invite-only. Slots for real quotes and logos show
 *  as dashed boxes in development only, and are left out of a production build until filled. */

// The bundled sample ad as shot, and the render the app made of its one recorded edit
// (scripts/landing_sample.py makes it again). Public static files: no account, nothing else served.
const BEFORE = '/sample-ad.mp4'
const AFTER = '/sample-ad-after.mp4'

const SHOW_SLOTS = import.meta.env.DEV

function Slot({ label }: { label: string }) {
  if (!SHOW_SLOTS) return null
  return (
    <div className="flex min-h-[96px] items-center justify-center rounded-xl border-[1.5px] border-dashed border-line2 p-4 text-center" data-testid="landing-slot">
      <span className="tag text-muted-foreground">Slot: {label} (empty, development only)</span>
    </div>
  )
}

const still = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const scrollTo = (id: string) => () => document.getElementById(id)?.scrollIntoView({ behavior: still() ? 'auto' : 'smooth', block: 'start' })

const money = (n: number, cur: 'usd' | 'inr') =>
  cur === 'usd' ? `$${Number.isInteger(n) ? n : n.toFixed(2)}` : `₹${Math.round(n).toLocaleString('en-IN')}`

function Demo() {
  const [which, setWhich] = useState<'before' | 'after'>('before')
  return (
    <figure className="m-0 flex min-w-0 flex-col gap-3" aria-labelledby="demo-h" data-testid="landing-demo">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="demo-h" className="disp m-0 text-[22px] font-bold">The sample ad</h3>
        <div className="segs" role="group" aria-label="Which version plays">
          <button type="button" className="seg pointer-coarse:h-11" aria-pressed={which === 'before'} onClick={() => setWhich('before')}>Before</button>
          <button type="button" className="seg pointer-coarse:h-11" aria-pressed={which === 'after'} onClick={() => setWhich('after')}>After</button>
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border-[1.5px] border-foreground bg-pic">
        <video key={which} className="block aspect-video w-full" src={which === 'before' ? BEFORE : AFTER} controls playsInline preload="metadata"
          aria-label={which === 'before' ? 'The sample ad as shot' : 'The sample ad after Voltage changed the line'} data-testid="demo-video" />
      </div>
      <figcaption className="flex flex-col gap-1.5">
        <span className="disp text-[20px] leading-snug font-semibold">
          {which === 'before' ? <>“Get 20% off today only.”</> : <>“Get <del className="text-muted-foreground">20%</del> <ins className="px-1">30%</ins> off today only.”</>}
        </span>
        <span className="text-sm text-muted-foreground">
          {which === 'before'
            ? 'As shot. The ask: make the offer 30% off.'
            : 'Voltage changed the line and voiced it. This clip has 1.4 s of the speaker, too little to clone, so the take is a stock voice. The picture is a placeholder card; only the voice changed.'}
        </span>
      </figcaption>
    </figure>
  )
}

// Run 5 item 9: the three steps across a campaign, for ad teams and agencies.
const STEPS: [string, string][] = [
  ['Put the campaign in a project', 'Upload every cut of the ad: each size, each length, each market. Voltage reads who speaks, what they say, and when.'],
  ['Say the change once', 'Type it the way you would brief an editor: "Make every offer line say 25% off." Voltage plans it for every video and shows the cost before anything is spent.'],
  ['Review and export them all', 'Hear each video\'s new line and add the ones that pass. Then export every video at once, in 16:9, 9:16 or 1:1.'],
]

// Editing one video: the second section, under the campaign story.
const ONE_VIDEO: [string, string][] = [
  ['Upload a video', 'Up to 10 minutes, with speech or none.'],
  ['Say what it should say', 'Voltage proposes changes line by line. Hear each take in place before anything is added.'],
  ['Add it and export', 'Add the takes you like and download an MP4.'],
]

// What the hero shows: an example campaign, one change across its videos. Words only, no numbers it did not measure.
const EXAMPLE_ADS: { name: string; hindi?: boolean }[] = [
  { name: 'Diwali offer, 16:9' },
  { name: 'Diwali offer, 9:16 reel' },
  { name: 'Diwali offer, 6 s bumper' },
  { name: 'Diwali offer, Hindi version', hindi: true },
]

function CampaignExample() {
  return (
    <figure className="m-0 flex min-w-0 flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-4 shadow-volt sm:p-5" aria-label="An example: one change across four ads" data-testid="landing-campaign">
      <div className="flex flex-col gap-1 rounded-lg bg-sunk px-3 py-2.5">
        <span className="tag text-muted-foreground">You say, once</span>
        <span className="text-[15px] font-medium">“Make every offer line say 25% off.”</span>
      </div>
      <ul className="m-0 flex list-none flex-col p-0">
        {EXAMPLE_ADS.map((a) => (
          <li key={a.name} className="flex flex-col gap-1 border-t border-line py-2.5 first:border-t-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-semibold">{a.name}</span>
              <span className="stamp">Ready to review</span>
            </span>
            {a.hindi
              ? <span className="text-[15px]" lang="hi">“आज ही <del className="text-muted-foreground">20%</del> <ins className="px-1">25%</ins> छूट पाएं।”</span>
              : <span className="text-[15px]">“Get <del className="text-muted-foreground">20%</del> <ins className="px-1">25%</ins> off today only.”</span>}
          </li>
        ))}
      </ul>
      <figcaption className="text-sm text-muted-foreground">An example campaign. Each ad keeps its speaker's voice and its picture; only the line changes.</figcaption>
    </figure>
  )
}

function OneVideo() {
  return (
    <section id="one-video" className="flex scroll-mt-20 flex-col gap-5" aria-labelledby="one-h" data-testid="landing-one-video">
      <div className="flex max-w-[680px] flex-col gap-2">
        <h2 id="one-h" className="disp m-0 text-[32px] leading-tight font-bold">Or change one video</h2>
        <p className="m-0 text-muted-foreground">
          The same editor works on a single video. Tell Voltage what the video should say: it rewrites the line,
          voices it in the speaker's own voice, and keeps the picture moving. No reshoot.
        </p>
      </div>
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Demo />
        <ol className="m-0 flex list-none flex-col gap-3 p-0" aria-label="Changing one video">
          {ONE_VIDEO.map(([h, t], i) => (
            <li key={h} className="flex gap-3 rounded-xl border border-line2 bg-card p-4">
              <span className="stamp quiet self-start" aria-hidden="true">{i + 1}</span>
              <span className="flex flex-col gap-1"><h3 className="disp m-0 text-lg font-bold">{h}</h3><span className="text-muted-foreground">{t}</span></span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function Features({ languages }: { languages: boolean | null }) {
  const items: [string, string, ReactNode?][] = [
    ['One change, every video', 'Offers, prices, dates and calls to action, changed across a whole campaign in one go. You see the cost first.'],
    ['Language versions', 'The same video with every line in Hindi, Hinglish, Tamil or Marathi, or in English.',
      languages === false ? <span className="stamp need" key="s">On request</span> : undefined],
    ['Every size at once', 'Export each video for YouTube, Reels and the feed, with captions if you want them, as one download.'],
    ['Replace a line', 'Change the words of a spoken line, voiced in the speaker\'s own voice or one you pick.'],
    ['Add a voice-over', 'Add a line over the picture, or where the picture makes room. Silent clips work too.'],
    ['Your own voice', 'Record ten seconds on the Voices page, then say "in my voice" in any video.'],
  ]
  return (
    <section className="flex flex-col gap-5" aria-labelledby="what-h">
      <h2 id="what-h" className="disp m-0 text-[32px] leading-tight font-bold">What Voltage does</h2>
      <ul className="m-0 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2">
        {items.map(([h, t, extra]) => (
          <li key={h} className="flex flex-col gap-1.5 rounded-xl border-[1.5px] border-foreground bg-card p-5">
            <span className="flex flex-wrap items-center gap-2"><h3 className="disp m-0 text-lg font-bold">{h}</h3>{extra}</span>
            <p className="m-0 text-muted-foreground">{t}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Pricing({ pricing, error, retry }: { pricing: PublicPricing | null; error: string | null; retry: () => void }) {
  const [cur, setCur] = useState<'usd' | 'inr'>('usd')
  return (
    <section id="pricing" className="flex scroll-mt-20 flex-col gap-5" aria-labelledby="pricing-h" data-testid="landing-pricing">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="pricing-h" className="disp m-0 text-[32px] leading-tight font-bold">Pricing</h2>
        <div className="flex gap-2" role="group" aria-label="Currency">
          <button type="button" className="pill pointer-coarse:h-11" aria-pressed={cur === 'usd'} onClick={() => setCur('usd')}>USD</button>
          <button type="button" className="pill pointer-coarse:h-11" aria-pressed={cur === 'inr'} onClick={() => setCur('inr')}>INR</button>
        </div>
      </div>
      {error && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {error}<button type="button" className="btn sm" onClick={retry}>Try again</button>
        </div>
      )}
      {!error && !pricing && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the prices…</p>}
      {pricing && (
        <>
          <p className="m-0 max-w-[680px]">
            Every new account starts with <strong className="tnum">{pricing.trial_credits}</strong> free credits, and they do not lapse.
            One credit pays for $1 of work at the vendors' prices: transcribing, voicing a line, Voltage's thinking.
          </p>
          <ul className="m-0 grid list-none grid-cols-1 gap-4 p-0 md:grid-cols-3">
            {pricing.plans.map((p) => (
              <li key={p.plan_id} className="flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-5" data-testid="plan-card">
                <h3 className="disp m-0 text-xl font-bold">{p.name}</h3>
                <span className="disp tnum text-[32px] leading-none font-bold">{money(cur === 'usd' ? p.usd : p.inr, cur)}<span className="text-base font-normal text-muted-foreground"> a month</span></span>
                <span className="tnum">{p.credits} credits a month</span>
                <p className="m-0 text-sm text-muted-foreground">{p.blurb}</p>
              </li>
            ))}
          </ul>
          <div className="flex flex-col gap-2 rounded-xl border border-line2 bg-sunk p-5">
            <h3 className="disp m-0 text-lg font-bold">Top-ups</h3>
            <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-1 p-0">
              {pricing.topups.map((t) => <li key={t.credits} className="tnum" data-testid="topup">{t.credits} credits for {money(cur === 'usd' ? t.usd : t.inr, cur)}</li>)}
            </ul>
            <p className="m-0 text-sm text-muted-foreground">A top-up's credits last {pricing.topup_months} months. A month's unused plan credits lapse when the month ends.</p>
          </div>
          <p className="m-0 text-sm text-muted-foreground">
            Prices before tax; in India, GST is added on the invoice.
            {pricing.test_mode && ' Payments are in test mode for now: no card is asked for and no money moves.'}
          </p>
        </>
      )}
    </section>
  )
}

function Faq({ pricing }: { pricing: PublicPricing | null }) {
  const trial = pricing ? `${pricing.trial_credits} free credits` : 'free credits'
  const qa: [string, string][] = [
    ['What is a credit?', 'One credit pays for $1 of work at the vendors\' prices: Claude for thinking, ElevenLabs for voices, Whisper for the transcript. Each step\'s cost shows in the trace and on the Usage page, and a failed vendor call is refunded.'],
    ['Is there a free trial?', `Yes. Every new account starts with ${trial}, and they never lapse. No card is needed to start.`],
    ['What counts as a minute?', 'Voltage charges credits for the work, not minutes of video, so a minute costs more when more of it changes. Once your exports have a measured cost, the Billing page shows about how many minutes your credits buy. A video can be up to 10 minutes and 2 GB.'],
    ['Whose voice can I clone?', 'Only a voice you have the right to use. Voltage clones a speaker from about ten clean seconds of their own speech, after you confirm consent and they read a short sentence aloud. It will not clone public figures. Withdraw consent in the editor and the clone is deleted at the voice service at once. Every export is marked as made with Voltage.'],
    ['How do I delete my data?', 'Settings has Download my data, a zip of every record of yours, and Delete my data, which deletes your account and everything in it.'],
    ['Which languages?', `Language versions make the same video with every line in Hindi, Hinglish, Tamil or Marathi, or in English for a video that is not in English.${pricing && !pricing.languages ? ' For now they are turned on per account: ask when you request access.' : ''}`],
  ]
  return (
    <section id="faq" className="flex scroll-mt-20 flex-col gap-4" aria-labelledby="faq-h" data-testid="landing-faq">
      <h2 id="faq-h" className="disp m-0 text-[32px] leading-tight font-bold">Questions</h2>
      <div className="flex flex-col border-t border-line2">
        {qa.map(([q, a]) => (
          <details key={q} className="group border-b border-line2 py-3">
            <summary className="disp flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-3 text-lg font-semibold focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ring/50">
              {q}<span aria-hidden="true" className="tnum text-muted-foreground group-open:rotate-45">+</span>
            </summary>
            <p className="m-0 max-w-[720px] pt-1 pb-2 text-muted-foreground">{a}</p>
          </details>
        ))}
      </div>
    </section>
  )
}

function RequestAccess() {
  const id = useId()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [useCase, setUseCase] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setFieldError(null); setError(null)
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) { setFieldError('Enter an email address, like you@example.com.'); document.getElementById(`${id}-email`)?.focus(); return }
    setBusy(true)
    try {
      const r = await joinWaitlist({ email: email.trim(), ...(name.trim() ? { name: name.trim() } : {}), ...(useCase.trim() ? { use_case: useCase.trim() } : {}) })
      setDone(r.message)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setFieldError(said(err, 'Enter an email address.'))
      else setError(said(err, 'That did not go through. Try again in a minute.'))
    } finally { setBusy(false) }
  }

  return (
    <section id="request-access" className="flex scroll-mt-20 flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-[22px] shadow-volt" aria-labelledby="access-h" data-testid="landing-access">
      <h2 id="access-h" className="disp m-0 text-[32px] leading-tight font-bold">Request access</h2>
      <p className="m-0 text-muted-foreground">Voltage is invite-only for now. Leave your email and we will send an invite when there is a place.</p>
      {done ? (
        <p className="m-0 rounded-md bg-sunk px-3 py-2 font-medium" role="status" data-testid="access-done">{done}</p>
      ) : (
        <form className="flex max-w-[520px] flex-col gap-3" onSubmit={submit} noValidate aria-label="Request access">
          <label className="flex flex-col gap-1" htmlFor={`${id}-email`}>
            <span className="font-medium">Email</span>
            <input id={`${id}-email`} className="h-11 rounded-md border-[1.5px] border-foreground bg-background px-3" type="email" autoComplete="email" required
              value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={fieldError ? true : undefined} aria-describedby={fieldError ? `${id}-email-error` : undefined} />
          </label>
          {fieldError && <p id={`${id}-email-error`} className="m-0 text-sm text-destructive">{fieldError}</p>}
          <label className="flex flex-col gap-1" htmlFor={`${id}-name`}>
            <span className="font-medium">Name <span className="font-normal text-muted-foreground">(optional)</span></span>
            <input id={`${id}-name`} className="h-11 rounded-md border-[1.5px] border-line2 bg-background px-3" autoComplete="name" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1" htmlFor={`${id}-use`}>
            <span className="font-medium">What do you make? <span className="font-normal text-muted-foreground">(optional)</span></span>
            <textarea id={`${id}-use`} className="min-h-[88px] rounded-md border-[1.5px] border-line2 bg-background px-3 py-2" maxLength={1000} value={useCase} onChange={(e) => setUseCase(e.target.value)} />
          </label>
          {error && <p className="m-0 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>}
          <button type="submit" className="btn volt self-start" disabled={busy}>{busy ? 'Sending…' : 'Request access'}</button>
        </form>
      )}
    </section>
  )
}

export function LandingPage() {
  const [pricing, setPricing] = useState<PublicPricing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    setError(null)
    getPricing().then(setPricing).catch((e) => setError(said(e, 'The prices could not be read.')))
  }, [])
  useEffect(() => { load() }, [load])
  // Until the server says, assume invite-only (the launch setting): the form is the safer default.
  const inviteOnly = pricing?.invite_only ?? true

  const cta = inviteOnly
    ? <button type="button" className="btn volt lg shine" onClick={scrollTo('request-access')}>Request access</button>
    : <a className="btn volt lg shine no-underline" href="#login">Make an account</a>

  return (
    <div className="min-h-dvh bg-background text-foreground" data-testid="landing-page">
      <header className="sticky top-0 z-10 flex h-[62px] items-center gap-3 border-b-[1.5px] border-foreground bg-card px-4 sm:gap-5 sm:px-6">
        <Wordmark href={null} />
        <nav aria-label="Sections" className="ml-2 hidden items-center gap-4 md:flex">
          <button type="button" className="act" onClick={scrollTo('how')}>How it works</button>
          <button type="button" className="act" onClick={scrollTo('one-video')}>One video</button>
          <button type="button" className="act" onClick={scrollTo('pricing')}>Pricing</button>
          <button type="button" className="act" onClick={scrollTo('faq')}>Questions</button>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <a className="btn sm no-underline pointer-coarse:h-11" href="#login">Sign in</a>
          {inviteOnly
            ? <button type="button" className="btn volt sm pointer-coarse:h-11" onClick={scrollTo('request-access')}>Request access</button>
            : <a className="btn volt sm no-underline pointer-coarse:h-11" href="#login">Make an account</a>}
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1120px] flex-col gap-16 px-4 pt-10 pb-16 sm:px-6 sm:pt-14">
        <section className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-6">
            <span className="tag text-muted-foreground">For ad teams and agencies</span>
            <h1 className="disp m-0 text-[clamp(40px,6vw,68px)] leading-[1.06] font-bold">
              Change every ad <ins className="rounded-md px-2">at once.</ins>
            </h1>
            <p className="m-0 max-w-[560px] text-lg leading-[1.55] text-muted-foreground">
              Offers, prices, languages. Say the change once and Voltage rewrites the line in every video of the campaign,
              voices it in the speaker's own voice, and keeps the picture. No reshoot, no edit suite.
            </p>
            <div className="flex flex-wrap items-center gap-3">{cta}<span className="tag text-faint">Every video in a project · you see the cost first</span></div>
          </div>
          <CampaignExample />
        </section>

        <Slot label="customer quote" />

        <section id="how" className="flex scroll-mt-20 flex-col gap-5" aria-labelledby="how-h">
          <h2 id="how-h" className="disp m-0 text-[32px] leading-tight font-bold">How it works for a campaign</h2>
          <ol className="m-0 grid list-none grid-cols-1 gap-4 p-0 md:grid-cols-3">
            {STEPS.map(([h, t], i) => (
              <li key={h} className="flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-5">
                <span className="stamp self-start" aria-hidden="true">{i + 1}</span>
                <h3 className="disp m-0 text-lg font-bold">{h}</h3>
                <p className="m-0 text-muted-foreground">{t}</p>
              </li>
            ))}
          </ol>
        </section>

        <OneVideo />

        <Features languages={pricing ? pricing.languages : null} />

        <Slot label="customer logos" />

        <Pricing pricing={pricing} error={error} retry={load} />

        <Faq pricing={pricing} />

        {inviteOnly ? <RequestAccess /> : (
          <section className="flex flex-col items-start gap-3" aria-labelledby="start-h">
            <h2 id="start-h" className="disp m-0 text-[32px] leading-tight font-bold">Try it on your own video</h2>
            <a className="btn volt lg no-underline" href="#login">Make an account</a>
          </section>
        )}
      </main>

      <footer className="border-t-[1.5px] border-foreground bg-card">
        <div className="mx-auto flex w-full max-w-[1120px] flex-wrap items-center justify-between gap-3 px-4 py-6 sm:px-6">
          <Wordmark href={null} size={22} />
          <LegalLinks />
        </div>
      </footer>
    </div>
  )
}
