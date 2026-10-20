import { useEffect, useRef, useState } from 'react'
import type { PublicComment, PublicShare, ReviewVideo } from '../types'
import { reviewAnswer, reviewComment, sharedFileUrl } from '../api'
import { formatDate } from '../lib/dates'
import { clock } from '../transcript/format'
import { said } from '../pages/fmt'

const NAME_KEY = 'voltage-reviewer-name'
const readName = () => { try { return localStorage.getItem(NAME_KEY) ?? '' } catch { return '' } }
const keepName = (n: string) => { try { localStorage.setItem(NAME_KEY, n) } catch { /* private window: the name lives for this visit */ } }

/** One video under review: the version picker with what changed, the player
 *  (a watermark with the reviewer's name when download is off), comments
 *  pinned to the playing time, and the answer (Approve last). */
function ReviewVideoPanel({ token, video, reviewer, allowDownload, name, onChanged }: {
  token: string; video: ReviewVideo; reviewer: string | null; allowDownload: boolean; name: string; onChanged: (v: ReviewVideo) => void
}) {
  const [version, setVersion] = useState<number | null>(video.current_version)
  const [time, setTime] = useState(0)
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'comment' | 'approve' | 'changes' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [answerError, setAnswerError] = useState<string | null>(null)
  const player = useRef<HTMLVideoElement>(null)
  const picked = video.versions.find((v) => v.version === version) ?? video.versions[0] ?? null
  const who = reviewer ?? (name.trim() || null)

  const seek = (t: number, v: number | null) => {
    if (v != null && v !== version && video.versions.some((x) => x.version === v)) setVersion(v)
    requestAnimationFrame(() => { if (player.current) { player.current.currentTime = t; setTime(t) } })
  }
  const comment = async () => {
    if (!text.trim() || !picked) return
    setBusy('comment')
    setError(null)
    try {
      const made: PublicComment = await reviewComment(token, { video_id: video.video_id, at_s: time, text: text.trim(), version: picked.version, name: who ?? undefined })
      onChanged({ ...video, comments: [...video.comments, made].sort((a, b) => a.at_s - b.at_s || a.comment_id - b.comment_id) })
      setText('')
    } catch (e) {
      setError(said(e, 'Could not add the comment. Try again.'))
    } finally { setBusy(null) }
  }
  const answer = async (kind: 'approve' | 'changes') => {
    setBusy(kind)
    setAnswerError(null)
    try {
      const out = await reviewAnswer(token, kind, { video_id: video.video_id, version: picked?.version ?? null, note: note.trim() || undefined, name: who ?? undefined })
      onChanged({ ...video, answer: out.answer })
      setNote('')
    } catch (e) {
      setAnswerError(said(e, 'Could not send your answer. Try again.'))
    } finally { setBusy(null) }
  }

  return (
    <section className="flex flex-col gap-5" aria-label={video.title} data-testid="review-video">
      {video.versions.length > 1 && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-semibold" id={`ver-${video.video_id}`}>Version</span>
          <div className="segs" role="group" aria-labelledby={`ver-${video.video_id}`} data-testid="version-picker">
            {video.versions.map((v) => (
              <button key={v.version} type="button" className="seg" aria-pressed={picked?.version === v.version} onClick={() => setVersion(v.version)}>
                v{v.version}{v.version === video.current_version ? ' · latest' : ''}
              </button>
            ))}
          </div>
        </div>
      )}
      {!picked ? (
        <p className="m-0 rounded-xl border-[1.5px] border-dashed border-line2 p-5 text-muted-foreground" data-testid="review-empty">Nothing to watch yet. The video shows here once its first version is ready; this link keeps working.</p>
      ) : (
        <>
          <div className="relative aspect-video w-full overflow-hidden rounded-xl border-[1.5px] border-ink bg-pic" onContextMenu={allowDownload ? undefined : (e) => e.preventDefault()}>
            <video
              key={picked.file_id}
              ref={player}
              className="absolute inset-0 size-full bg-pic object-contain"
              src={sharedFileUrl(token, picked.file_id)}
              controls preload="metadata" playsInline
              controlsList={allowDownload ? undefined : 'nodownload'}
              aria-label={`${video.title}, version ${picked.version}`}
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
              onSeeked={(e) => setTime(e.currentTarget.currentTime)}
            />
            {/* Download off: the reviewer's name over the picture (a watermark burned into the file is for later). */}
            {!allowDownload && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden="true" data-testid="watermark">
                <span className="disp -rotate-12 text-[clamp(18px,4vw,34px)] font-bold text-ptext opacity-30 select-none">
                  {who ? `Review copy · ${who}` : 'Review copy'}
                </span>
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1.5 rounded-xl border-[1.5px] border-line2 bg-card p-4" data-testid="what-changed">
            <span className="tag text-faint">What changed in v{picked.version} · against {picked.against}</span>
            {picked.changes.length === 0
              ? <span className="text-sm text-muted-foreground">{picked.against === 'as shot' ? 'This is the video as shot.' : 'No lines changed; the sound or timing may have.'}</span>
              : <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-[15px]">{picked.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>}
            <span className="text-xs text-faint">Made {formatDate(picked.created_at)}</span>
          </div>
          {allowDownload && <a className="btn sm self-start" href={sharedFileUrl(token, picked.file_id, true)} download>Download v{picked.version}</a>}
        </>
      )}

      {video.read_only && (
        <p className="m-0 rounded-xl border-[1.5px] border-foreground bg-sunk p-4 text-[15px]" role="status" data-testid="review-closed">
          <span className="stamp quiet mr-2">Archived</span>{video.read_only}
        </p>
      )}

      {picked && !video.read_only && (
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); void comment() }} data-testid="comment-form">
          <label htmlFor={`c-${video.video_id}`} className="text-sm font-semibold">Comment at <span className="tnum">{clock(time)}</span> in v{picked.version}</label>
          <textarea id={`c-${video.video_id}`} rows={3} maxLength={2000} className="w-full resize-y rounded-lg border-[1.5px] border-line2 bg-background p-3 text-[15px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={text} onChange={(e) => setText(e.target.value)} placeholder="Pause where something should change and say what." />
          {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
          <button type="submit" className="btn sm self-end" disabled={!text.trim() || busy !== null} aria-busy={busy === 'comment' || undefined}>{busy === 'comment' ? 'Adding…' : `Add comment at ${clock(time)}`}</button>
        </form>
      )}

      <div className="flex flex-col gap-2">
        <span className="tag text-faint">Comments · {video.comments.length}</span>
        {video.comments.length === 0 ? <span className="text-sm text-muted-foreground">No comments yet.</span> : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0" data-testid="review-comments">
            {video.comments.map((c) => (
              <li key={c.comment_id} className="flex flex-col gap-1 rounded-lg border-[1.5px] border-line2 bg-card p-3" data-testid="review-comment">
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" className="tnum act p-0" onClick={() => seek(c.at_s, c.version)} aria-label={`Play from ${clock(c.at_s)}`}>{clock(c.at_s)}</button>
                  {c.version != null && <span className="tag text-faint">v{c.version}</span>}
                  <span className="text-sm font-semibold">{c.author}</span>
                  {c.status === 'resolved' && <span className="stamp in">Resolved</span>}
                </div>
                <p className="m-0 text-[15px] whitespace-pre-wrap">{c.text}</p>
                {c.replies.map((r, i) => (
                  <p key={i} className="m-0 border-l-2 border-line2 pl-3 text-sm"><span className="font-semibold">{r.author}</span> {r.text}</p>
                ))}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2.5 rounded-xl border-[1.5px] border-foreground bg-card p-4" data-testid="review-answer">
        <span className="disp text-lg font-bold">Your answer</span>
        {video.read_only && !video.answer && <span className="text-sm text-muted-foreground">Answers are closed while the project is archived.</span>}
        {video.answer && (
          <p className="m-0 text-sm" role="status" data-testid="answer-said">
            <span className={video.answer.answer === 'approved' ? 'stamp' : 'stamp need'}>{video.answer.answer === 'approved' ? 'Approved' : 'Changes asked'}</span>{' '}
            {video.answer.by} {video.answer.answer === 'approved' ? 'approved' : 'asked for changes on'}{video.answer.version ? ` v${video.answer.version}` : ''} {formatDate(video.answer.at)}.{video.read_only ? '' : ' You can still change your answer.'}
          </p>
        )}
        {video.read_only ? null : <>
        <label htmlFor={`n-${video.video_id}`} className="text-sm font-semibold">Note <span className="font-normal text-muted-foreground">Optional</span></label>
        <textarea id={`n-${video.video_id}`} rows={2} maxLength={2000} className="w-full resize-y rounded-lg border-[1.5px] border-line2 bg-background p-3 text-[15px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={note} onChange={(e) => setNote(e.target.value)} />
        {answerError && <p className="m-0 text-sm text-destructive" role="alert">{answerError}</p>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button type="button" className="btn sm" disabled={busy !== null} onClick={() => void answer('changes')} aria-busy={busy === 'changes' || undefined}>{busy === 'changes' ? 'Sending…' : 'Ask for changes'}</button>
          <button type="button" className="btn volt sm" disabled={busy !== null || !picked} onClick={() => void answer('approve')} aria-busy={busy === 'approve' || undefined}>{busy === 'approve' ? 'Approving…' : picked ? `Approve v${picked.version}` : 'Approve'}</button>
        </div>
        </>}
      </div>
    </section>
  )
}

/** C2: what a review link opens (no account): each video with its versions,
 *  comments and answer. A link that names no one asks for a name first
 *  (optional; kept in this browser). */
export function ReviewPage({ token, share }: { token: string; share: PublicShare & { review: NonNullable<PublicShare['review']> } }) {
  const [videos, setVideos] = useState(share.review.videos)
  const [current, setCurrent] = useState(share.review.videos[0]?.video_id ?? null)
  const [name, setName] = useState(readName)
  useEffect(() => { setVideos(share.review.videos) }, [share])
  const video = videos.find((v) => v.video_id === current) ?? null
  const reviewer = share.review.reviewer
  return (
    <div className="flex flex-col gap-6" data-testid="review-page">
      <div className="flex flex-col gap-1.5">
        <h1 className="disp m-0 text-[clamp(30px,4.5vw,46px)] leading-none font-bold">{share.title}</h1>
        <span className="text-sm text-muted-foreground" data-testid="share-meta">
          {reviewer ? `For ${reviewer} · ` : ''}{videos.length} {videos.length === 1 ? 'video' : 'videos'} to review · this link works until {formatDate(share.expires_at)}
        </span>
      </div>
      {!reviewer && (
        <label className="flex max-w-[360px] flex-col gap-1 text-sm font-semibold">Your name <span className="font-normal text-muted-foreground">Shown with your comments and answer</span>
          <input className="h-9 rounded-md border-[1.5px] border-line2 bg-background px-2.5 font-normal outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={name} maxLength={80} onChange={(e) => { setName(e.target.value); keepName(e.target.value) }} autoComplete="name" />
        </label>
      )}
      {videos.length > 1 && (
        <div className="segs flex-wrap self-start" role="group" aria-label="Videos">
          {videos.map((v) => <button key={v.video_id} type="button" className="seg" aria-pressed={current === v.video_id} onClick={() => setCurrent(v.video_id)}>{v.title}</button>)}
        </div>
      )}
      {videos.length === 0 && <p className="m-0 text-muted-foreground">There is nothing to review on this link any more.</p>}
      {video && (
        <ReviewVideoPanel key={video.video_id} token={token} video={video} reviewer={reviewer} allowDownload={share.review.allow_download} name={name}
          onChanged={(v) => setVideos((all) => all.map((x) => (x.video_id === v.video_id ? v : x)))} />
      )}
    </div>
  )
}
