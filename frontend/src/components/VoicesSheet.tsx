import { useRef, useState } from 'react'
import type { MyVoice } from '../types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, Mic, Trash2 } from 'lucide-react'

interface VoicesSheetProps {
  open: boolean
  voices: MyVoice[]
  onUpload: (name: string, file: File) => Promise<unknown>
  onDelete: (voiceId: string) => Promise<unknown>
  onClose: () => void
}

/** Your voices (20i): the ones you have uploaded under a name, and a form to
 *  add one — a recording of ten seconds or more, a name, and your word that
 *  the voice is yours or one you may use. Once kept, a voice is offered
 *  wherever a voice is picked, and "in my voice" means it to Voltage. */
export function VoicesSheet({ open, voices, onUpload, onDelete, onClose }: VoicesSheetProps) {
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const canUpload = name.trim() !== '' && file !== null && consent && busy === null

  const upload = async () => {
    if (!canUpload || !file) return
    setBusy('upload')
    setError(null)
    try {
      await onUpload(name.trim(), file)
      setName('')
      setFile(null)
      setConsent(false)
      if (fileInput.current) fileInput.current.value = ''
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The voice could not be made.')
    } finally {
      setBusy(null)
    }
  }
  const remove = async (voiceId: string) => {
    setBusy(voiceId)
    setError(null)
    try { await onDelete(voiceId) } catch (e) { setError(e instanceof Error ? e.message : 'The voice could not be removed.') } finally { setBusy(null) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg" aria-busy={busy !== null || undefined}>
        <DialogTitle>Your voices</DialogTitle>
        <DialogDescription>Upload a recording of your voice under a name. Then tell Voltage "say it in my voice", or pick it on any line.</DialogDescription>
        <div className="flex flex-col gap-5 text-sm">
          <section className="flex flex-col gap-2" aria-label="The voices you have">
            {voices.length === 0 ? (
              <p className="m-0 text-muted-foreground">No voice of yours yet.</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {voices.map((v) => (
                  <li key={v.voice_id} className="flex items-center gap-3 rounded-md border bg-card px-3 py-2">
                    <Mic className="size-4 shrink-0 text-primary" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate font-medium">{v.name}</span>
                    <span className="tnum text-xs text-muted-foreground">{Math.round(v.seconds)} s of you</span>
                    <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => void remove(v.voice_id)} disabled={busy !== null} aria-label={`Remove ${v.name}`}>
                      {busy === v.voice_id ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <form className="flex flex-col gap-3 rounded-md border bg-muted/40 p-3" aria-label="Add a voice" onSubmit={(e) => { e.preventDefault(); void upload() }}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="voice-name">Name it</Label>
              <Input id="voice-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ashish" maxLength={40} disabled={busy !== null} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="voice-file">A recording of you</Label>
              <input
                id="voice-file"
                ref={fileInput}
                type="file"
                accept="audio/*,video/*"
                className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-foreground hover:file:bg-accent pointer-coarse:file:py-2.5"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={busy !== null}
              />
              <p className="m-0 text-xs text-muted-foreground">Ten seconds or more of you speaking, on its own: a WAV, MP3, M4A, or a video with your voice. Quiet room, no music.</p>
            </div>
            <label className="flex items-start gap-2.5 text-sm">
              <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={consent} onChange={(e) => setConsent(e.target.checked)} disabled={busy !== null} />
              <span>This is my voice, or one I have the right to use. Voltage will make speech in it when I ask.</span>
            </label>
            {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
            <div className="flex items-center gap-2">
              <span className="flex-1 text-xs text-muted-foreground">Making a voice takes a voice slot, not characters.</span>
              <Button type="submit" disabled={!canUpload} aria-busy={busy === 'upload' || undefined}>
                {busy === 'upload' ? 'Making it…' : 'Keep this voice'}
              </Button>
            </div>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  )
}
