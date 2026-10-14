import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { Presence } from './Presence'
import { ThemeToggle } from './ThemeToggle'

interface LoadScreenProps {
  onLoad: (file: File) => void
  onLoadSample: () => void
  loading: boolean
  /** UX-6: how much of the upload has gone, 0..1; null while transcribing or unknown. */
  progress?: number | null
  error?: string | null
  /** Past projects, shown under the drop zone. */
  children?: ReactNode
  /** Phase 9c: who is signed in, with a way out. */
  who?: { name: string; picture?: string | null } | null
  onSignOut?: () => void
}

/** Your videos (UX-7f): a drop zone, the sample, and the projects as cards.
 *  The drop zone is a dashed outline that takes the ring colour and a quiet
 *  fill while a file is over it. */
export function LoadScreen({ onLoad, onLoadSample, loading, progress = null, error, children, who, onSignOut }: LoadScreenProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const dropped = (files: FileList | null) => {
    const file = files?.[0]
    if (file && !loading) onLoad(file)
  }

  /** Percent uploaded, or null while the size is unknown or the server is transcribing. */
  const known = progress !== null && progress < 1 ? Math.round(progress * 100) : null

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 items-center gap-3 border-b border-border bg-background px-4 sm:px-6">
        <span className="flex items-center gap-2 text-base font-semibold tracking-tight"><Presence size={14} />Voltage</span>
        <span className="flex-1" />
        <ThemeToggle />
        {who && (
          <span className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="who">
            {who.picture ? <img className="size-6 rounded-full" src={who.picture} alt="" referrerPolicy="no-referrer" /> : null}
            {who.name}
            {onSignOut && <Button variant="outline" size="sm" onClick={onSignOut}>Sign out</Button>}
          </span>
        )}
      </header>

      <main className="mx-auto flex w-full max-w-[1120px] flex-col gap-5 px-4 pt-5 pb-8 sm:gap-7 sm:px-6 sm:pt-8 sm:pb-12">
        <h1 className="m-0 text-3xl font-semibold tracking-tight">Your videos</h1>

        <section
          className={cn(
            'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-4 py-7 text-center transition-colors sm:px-6 sm:py-11',
            over && 'border-ring bg-accent',
          )}
          data-over={over || undefined}
          aria-label="Start a new video"
          aria-busy={loading || undefined}
          data-testid="drop-zone"
          onDragOver={(e) => { e.preventDefault(); if (!loading) setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); dropped(e.dataTransfer?.files ?? null) }}
        >
          <Upload className="size-7 text-muted-foreground" strokeWidth={1.5} aria-hidden="true" />
          <h2 className="m-0 text-xl font-semibold tracking-tight">Drop a video here</h2>
          <p className="m-0 text-base text-muted-foreground">Up to three minutes. With speech, or without any at all.</p>
          <input
            ref={inputRef}
            className="sr-only"
            type="file"
            accept="video/*"
            aria-label="Choose a video"
            disabled={loading}
            onChange={(e) => {
              const file = e.target.files?.[0]
              // Reset so re-picking the same file fires onChange again.
              e.target.value = ''
              if (file) onLoad(file)
            }}
          />
          <div className="mt-1 flex flex-wrap items-center justify-center gap-3">
            <Button onClick={() => inputRef.current?.click()} disabled={loading}>
              {loading ? 'Uploading…' : 'Choose a video'}
            </Button>
            <Button variant="outline" onClick={onLoadSample} disabled={loading}>Try the sample ad</Button>
          </div>
          {loading && (
            <div className="flex items-center gap-3" role="status">
              <Progress
                className={cn('w-32', known === null && 'animate-pulse [&>*]:transform-none!')}
                aria-label="Uploading"
                value={known}
              />
              <span className="text-sm text-muted-foreground">
                {known !== null
                  ? `Uploading, ${known}%.`
                  : 'Transcribing. This takes a little while for a long clip.'}
              </span>
            </div>
          )}
          {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
        </section>

        <div className="flex flex-col">{children}</div>
      </main>
    </div>
  )
}
