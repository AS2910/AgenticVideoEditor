import { useEffect, useRef, useState } from 'react'
import { track } from '../lib/analytics'
import type { ShareLink } from '../types'
import { createProjectReviewLink, createReviewLink, listProjectShares, listReviewLinks, revokeReviewLink, revokeShare } from '../api'
import { formatDate } from '../lib/dates'
import { useReturnFocus } from '../components/useReturnFocus'
import { said } from '../pages/fmt'

/** What the dialog sends: one video from the editor, or picked videos of a project. */
export type ReviewTarget =
  | { kind: 'video'; videoId: string; title: string }
  | { kind: 'project'; projectId: string; title: string; videos: { video_id: string; filename: string; stage_label?: string }[]; picked?: string[] }

const DAYS = [7, 30, 90] as const
const STATE_WORD: Record<ShareLink['state'], string> = { live: 'Live', revoked: 'Turned off', expired: 'Expired' }

async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); track('review.link_copied'); return true } catch { return false }
}

/** One review link: who it is for, its state, Copy link, Turn off. */
function LinkRow({ link, onRevoke }: { link: ShareLink; onRevoke: (l: ShareLink) => Promise<void> }) {
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const live = link.state === 'live'
  return (
    <li className="flex flex-col gap-1 border-t border-line py-2 first:border-t-0" data-testid="review-link" data-state={link.state}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={live ? 'stamp' : 'stamp quiet'}>{STATE_WORD[link.state]}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{link.name ?? 'No name'}{link.data?.email ? <span className="font-normal text-muted-foreground"> · {link.data.email}</span> : null}</span>
        {live && <button type="button" className="act" onClick={async () => { if (await copyText(link.url)) { setCopied(true); setTimeout(() => setCopied(false), 1800) } else setNote('Could not copy. Open the link and copy it from the address bar.') }}>{copied ? 'Copied' : 'Copy link'}</button>}
        {live && <button type="button" className="act" disabled={busy} onClick={async () => { setBusy(true); setNote(null); try { await onRevoke(link) } catch (e) { setNote(said(e, 'Could not turn the link off.')) } finally { setBusy(false) } }}>{busy ? 'Turning off…' : 'Turn off'}</button>}
      </div>
      <span className="text-xs text-muted-foreground">
        {link.data?.allow_download ? 'Download allowed' : 'Watch only'} · {live ? `works until ${formatDate(link.expires_at)}` : link.state === 'expired' ? `expired ${formatDate(link.expires_at)}` : 'turned off'}
      </span>
      {note && <span className="text-sm text-destructive" role="alert">{note}</span>}
    </li>
  )
}

/** C2 (projects.review): Send for review. A reviewer link to a video, or to
 *  the picked videos of a project, with an optional name and email, how long
 *  it works (30 days unless changed) and Allow download (off). Making it puts
 *  the videos In review; then Copy link. Every review link made before is
 *  listed with Copy link and Turn off. */
export function SendForReview({ target, onClose, onSent }: { target: ReviewTarget; onClose: () => void; onSent?: (link: ShareLink) => void }) {
  useReturnFocus()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [days, setDays] = useState<number>(30)
  const [download, setDownload] = useState(false)
  const [picked, setPicked] = useState<string[]>(target.kind === 'project' ? (target.picked ?? target.videos.map((v) => v.video_id)) : [])
  const [links, setLinks] = useState<ShareLink[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [made, setMade] = useState<ShareLink | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const load = () => {
    setLoadError(null)
    const read = target.kind === 'video'
      ? listReviewLinks(target.videoId).then((r) => r.links)
      : listProjectShares(target.projectId).then((r) => r.shares.filter((s) => s.role === 'reviewer'))
    read.then(setLinks).catch((e) => setLoadError(said(e, 'Could not read the links.')))
  }
  useEffect(load, [target.kind === 'video' ? target.videoId : target.projectId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  useEffect(() => { box.current?.querySelector<HTMLElement>('input')?.focus() }, [])

  const send = async () => {
    setBusy(true)
    setError(null)
    const body = { name: name.trim() || undefined, email: email.trim() || undefined, days, allow_download: download }
    try {
      const link = target.kind === 'video'
        ? await createReviewLink(target.videoId, body)
        : await createProjectReviewLink(target.projectId, { ...body, videos: picked })
      setMade(link)
      onSent?.(link)
      load()
    } catch (e) {
      setError(said(e, 'Could not make the link. Try again.'))
    } finally { setBusy(false) }
  }
  const revoke = async (l: ShareLink) => {
    if (target.kind === 'video') await revokeReviewLink(target.videoId, l.share_id)
    else await revokeShare(target.projectId, l.share_id)
    load()
  }
  const emailBad = email.trim() !== '' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((v) => v !== id) : [...p, id]))

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/60 p-4" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={box} role="dialog" aria-modal="true" aria-label="Send for review" className="rise flex max-h-[90dvh] w-full max-w-[560px] flex-col gap-4 overflow-y-auto rounded-xl border-[1.5px] border-ink bg-card p-6 shadow-volt-lg sm:px-7" data-testid="send-review">
        <div className="flex flex-col gap-0.5">
          <span className="tag text-faint">Send for review</span>
          <span className="disp truncate text-[26px] font-bold" title={target.title}>{target.title}</span>
          <span className="text-muted-foreground">Anyone with the link can watch, comment at a moment, and approve or ask for changes. No account needed.</span>
        </div>

        {made ? (
          <div className="flex flex-col gap-2 rounded-lg border-[1.5px] border-ink bg-sunk p-3.5" data-testid="review-made">
            <span className="text-sm font-semibold">Link made. {target.kind === 'video' ? 'The video is' : picked.length === 1 ? 'The video is' : 'The videos are'} In review.</span>
            <div className="flex flex-wrap items-center gap-2">
              <input readOnly className="tnum h-8 min-w-0 flex-[1_1_220px] rounded-md border-[1.5px] border-line2 bg-background px-2 text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={made.url} aria-label="Review link" onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="btn volt sm" onClick={async () => { if (await copyText(made.url)) { setCopied(true); setTimeout(() => setCopied(false), 1800) } else setError('Could not copy. Select the link and copy it.') }}>{copied ? 'Copied' : 'Copy link'}</button>
            </div>
            {made.data?.email && <span className="text-xs text-muted-foreground">An email with the link is on its way to {made.data.email}.</span>}
            <button type="button" className="act self-start" onClick={() => { setMade(null); setName(''); setEmail('') }}>Make another link</button>
          </div>
        ) : (
          <form className="flex flex-col gap-3.5" onSubmit={(e) => { e.preventDefault(); if (!emailBad && (target.kind === 'video' || picked.length > 0)) void send() }}>
            {target.kind === 'project' && (
              <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
                <legend className="mb-1 text-sm font-semibold">Videos</legend>
                {target.videos.length === 0 && <span className="text-sm text-muted-foreground">No videos here yet.</span>}
                {target.videos.map((v) => (
                  <label key={v.video_id} className="flex min-h-8 items-center gap-2.5 text-sm">
                    <input type="checkbox" className="size-4 accent-volt" checked={picked.includes(v.video_id)} onChange={() => toggle(v.video_id)} />
                    <span className="min-w-0 flex-1 truncate">{v.filename}</span>
                    {v.stage_label && <span className="tag text-faint">{v.stage_label}</span>}
                  </label>
                ))}
              </fieldset>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm font-semibold">Reviewer's name <span className="font-normal text-muted-foreground">Optional</span>
                <input className="h-9 rounded-md border-[1.5px] border-line2 bg-background px-2.5 font-normal outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoComplete="off" />
              </label>
              <label className="flex flex-col gap-1 text-sm font-semibold">Their email <span className="font-normal text-muted-foreground">Optional. Told when a new version is ready</span>
                <input type="email" className="h-9 rounded-md border-[1.5px] border-line2 bg-background px-2.5 font-normal outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={emailBad || undefined} aria-describedby={emailBad ? 'review-email-bad' : undefined} autoComplete="off" />
                {emailBad && <span id="review-email-bad" className="font-normal text-destructive">That email address does not look right.</span>}
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-semibold" id="review-days">The link works for</span>
              <div className="segs" role="group" aria-labelledby="review-days">
                {DAYS.map((d) => <button key={d} type="button" className="seg" aria-pressed={days === d} onClick={() => setDays(d)}>{d} days</button>)}
              </div>
            </div>
            <label className="flex items-start gap-2.5 text-sm">
              <input type="checkbox" className="mt-0.5 size-4 accent-volt" checked={download} onChange={(e) => setDownload(e.target.checked)} />
              <span><span className="font-semibold">Allow download</span><span className="block text-muted-foreground">Off: the reviewer can watch but not save the file, and their name shows over the picture.</span></span>
            </label>
            {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button type="button" className="btn sm" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn volt sm" disabled={busy || emailBad || (target.kind === 'project' && picked.length === 0)} aria-busy={busy || undefined}>
                {busy ? 'Making the link…' : target.kind === 'project' ? `Make the link for ${picked.length} ${picked.length === 1 ? 'video' : 'videos'}` : 'Make the link'}
              </button>
            </div>
          </form>
        )}

        <div className="flex flex-col gap-1 border-t border-line pt-3">
          <span className="tag text-faint">Review links</span>
          {loadError ? (
            <div className="flex items-center gap-2 text-sm" role="alert"><span className="flex-1 text-destructive">{loadError}</span><button type="button" className="btn sm" onClick={load}>Try again</button></div>
          ) : links === null ? (
            <span className="text-sm text-muted-foreground" role="status">Reading the links…</span>
          ) : links.length === 0 ? (
            <span className="text-sm text-muted-foreground">No review links yet.</span>
          ) : (
            <ul className="m-0 list-none p-0">{links.map((l) => <LinkRow key={l.share_id} link={l} onRevoke={revoke} />)}</ul>
          )}
        </div>
        {made && <button type="button" className="btn sm self-end" onClick={onClose}>Done</button>}
      </div>
    </div>
  )
}
