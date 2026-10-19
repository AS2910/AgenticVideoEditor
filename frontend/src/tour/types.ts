/** A tour is data. Each step points at one or more `data-tour` targets on the
 *  page, says what to do there, and names how it moves on: the coach card's
 *  action, or an app event the host reports with `tour.notify(event)`. */
export interface TourStep {
  /** The `data-tour` name of the control the ring goes around. */
  target?: string
  /** Several targets: the ring covers their union (a row and a switch at once). */
  targets?: string[]
  title: string
  body: string
  /** The one-line cue under the body: "→ Click Send". */
  hint?: string
  /** The coach card's action button. */
  action: string
  /** 'click' moves on when the action is pressed; an event waits for the host. */
  advanceOn: 'click' | { event: string }
}

export interface TourCard { tag?: string; title: string; mark?: string; body: string; primary: string; secondary?: string }

export interface Tour {
  id: string
  steps: TourStep[]
  /** The opening card; without one the tour starts on its first step. */
  welcome?: TourCard
  /** The closing card; without one the tour just ends. `primaryHref` makes the primary a link. */
  done?: TourCard & { primaryHref?: string }
  /** Its progress is saved (the guided run); the short tours are not. */
  remember?: boolean
}

export type TourPhase = 'welcome' | 'step' | 'done' | 'skipped'

export interface TourProgress { step: number; finished: boolean; skipped: boolean }

export const stepTargets = (s: TourStep | null | undefined): string[] =>
  s ? [...(s.target ? [s.target] : []), ...(s.targets ?? [])] : []
