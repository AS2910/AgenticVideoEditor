import { useEffect, useState } from 'react'
import type { PublicShare } from '../types'
import { openShare, sharedFileUrl, sharedZipUrl } from '../api'
import { formatDate } from '../lib/dates'
import { clock } from '../transcript/format'
import { said } from './fmt'
import { Wordmark } from './Shell'
import { fileSize } from '../lib/exports'

/** F6/B3: what a share link opens, with no account: every file with a
 *  preview player and Download, Download all (.zip), when the link expires.
 *  An expired, turned-off or broken link says so plainly. */
export function SharePage({ token }: { token: string }) {
  const [share, setShare] = useState<PublicShare | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true
    setError(null)
    openShare(token).then((s) => { if (live) setShare(s) }).catch((e) => { if (live) setError(said(e, 'Could not open this link. Try again in a moment.')) })
    return () => { live = false }
  }, [token, tick])
  useEffect(() => { document.title = share ? `${share.title} · Voltage` : 'Shared from Voltage' }, [share])

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="flex min-h-[62px] items-center gap-4 border-b-[1.5px] border-foreground bg-card px-4 py-2.5 sm:px-6">
        <Wordmark href={null} />
        <span className="tag text-faint">Shared files</span>
      </header>
      <main className="mx-auto flex w-full max-w-[960px] flex-col gap-6 px-4 pt-9 pb-20 sm:px-6">
        {!share && !error && <p className="m-0 text-muted-foreground" role="status">Opening the link…</p>}
        {error && (
          <div className="flex flex-col items-start gap-3" role="alert" data-testid="share-refused">
            <h1 className="disp m-0 text-2xl font-bold">This link does not open</h1>
            <p className="m-0 max-w-[560px] text-[15px]">{error}</p>
            <button type="button" className="btn sm" onClick={() => setTick((t) => t + 1)}>Try again</button>
          </div>
        )}
        {share && (
          <>
            <div className="flex flex-col gap-1.5">
              <h1 className="disp m-0 text-[clamp(30px,4.5vw,46px)] leading-none font-bold">{share.title}</h1>
              <span className="text-sm text-muted-foreground" data-testid="share-meta">
                {share.files.length} {share.files.length === 1 ? 'file' : 'files'}{share.exported_at ? ` · exported ${formatDate(share.exported_at)}` : ''} · this link works until {formatDate(share.expires_at)}
              </span>
            </div>
            {share.files.length === 0 ? <p className="m-0 text-muted-foreground" data-testid="share-empty">Nothing is ready here yet. Check back once the files are made.</p> : (
              <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4 p-0">
                {share.files.map((f) => (
                  <li key={f.file_id} className="flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-3" data-testid="share-file">
                    <video className="aspect-video w-full rounded-[10px] border-[1.5px] border-ink bg-pic object-contain" src={sharedFileUrl(token, f.file_id)} controls preload="metadata" playsInline aria-label={`Preview ${f.name}`} />
                    {f.label && <span className="text-sm font-semibold">{f.label}</span>}
                    <span className="tnum truncate text-xs text-muted-foreground" title={f.name}>{f.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="tnum flex-1 text-xs text-faint">{fileSize(f.size)}{f.duration ? ` · ${clock(f.duration)}` : ''}</span>
                      <a className="btn sm" href={sharedFileUrl(token, f.file_id, true)} download={f.name} aria-label={`Download ${f.name}`}>Download</a>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {share.files.length > 1 && <a className="btn volt self-start" href={sharedZipUrl(token)} download>Download all (.zip)</a>}
          </>
        )}
      </main>
    </div>
  )
}
