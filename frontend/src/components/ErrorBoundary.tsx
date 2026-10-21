import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { reportError } from '../lib/errors'

/** G8: when a screen throws while drawing, say so plainly, report it, and offer a reload,
 *  instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { broken: boolean }> {
  state = { broken: false }

  static getDerivedStateFromError(): { broken: boolean } {
    return { broken: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportError({ message: error.message || String(error), stack: `${error.stack ?? ''}\n${info.componentStack ?? ''}`, kind: 'boundary' })
  }

  render(): ReactNode {
    if (!this.state.broken) return this.props.children
    return (
      <main className="grid min-h-dvh place-items-center bg-background px-4 text-foreground">
        <div className="flex max-w-[460px] flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" role="alert" data-testid="error-boundary">
          <h1 className="disp m-0 text-[26px] font-bold">Something broke on this screen</h1>
          <p className="m-0 text-muted-foreground">Your work is saved. We have been told what happened. Reload the page to carry on.</p>
          <button type="button" className="btn volt self-start" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </main>
    )
  }
}
