import { Zap } from 'lucide-react'
import { quickRoute } from '../transcript/fastpath'

/** Run 5 item 6: under the line editor, which way Enter will go. A small
 *  change in the line's own voice is voiced straight away (one take, no
 *  planning); anything bigger goes to Voltage, which plans it first. */
export function QuickEditHint({ before, after, voiceChanged }: { before: string; after: string; voiceChanged: boolean }) {
  const route = quickRoute(before, after, voiceChanged)
  if (route.changed === 0 && !voiceChanged) return null
  return (
    <p className="m-0 flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="quick-edit-hint" data-route={route.fast ? 'fast' : 'full'}>
      {route.fast
        ? <><Zap size={14} aria-hidden="true" className="shrink-0" />Small change: Enter voices it straight away.</>
        : <>Voltage will plan this one ({route.reason}).</>}
    </p>
  )
}
