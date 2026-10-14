import { LogIn } from 'lucide-react'
import { loginUrl } from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Presence } from './Presence'

/** Phase 9c: the door, when sign-in is on. */
export function SignIn({ error }: { error?: string | null }) {
  return (
    <div className="flex min-h-dvh flex-col items-center bg-background text-foreground">
      <header className="flex h-14 w-full items-center px-6">
        <span className="flex items-center gap-2 text-base font-semibold tracking-tight"><Presence size={14} />Voltage</span>
      </header>
      <main className="flex w-full flex-col items-center">
        <div className="mt-[clamp(32px,14vh,140px)] flex w-[min(640px,100%-32px)] flex-col gap-4">
          <h1 className="m-0 text-balance text-3xl font-semibold tracking-tight sm:text-4xl">Change what's said in a video you've already shot.</h1>
          <p className="m-0 text-base text-muted-foreground">
            Sign in to keep your projects, your spend and the voices you make to yourself.
          </p>
          <Card className="gap-3 rounded-lg p-4">
            <Button asChild className="self-start">
              <a href={loginUrl}>
                <LogIn aria-hidden="true" />
                Sign in with Google
              </a>
            </Button>
            <p className="m-0 text-sm text-muted-foreground">Nothing is uploaded until you are in. Your account is used only to tell your projects apart.</p>
            {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
          </Card>
        </div>
      </main>
    </div>
  )
}
