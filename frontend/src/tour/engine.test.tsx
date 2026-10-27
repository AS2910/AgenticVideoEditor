import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TourLayer, TourProvider, useTour } from './engine'
import { guidedRun, showMe } from './tours'
import { measure } from './measure'
import type { Tour, TourProgress } from './types'

/** jsdom lays nothing out: give every `data-tour` element a box of its own. */
beforeEach(() => {
  const real = Element.prototype.getBoundingClientRect
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    const name = this.getAttribute('data-tour')
    if (!name) return real.call(this)
    const i = name.length
    return { left: 100 + i, top: 200, width: 300, height: 60, right: 400 + i, bottom: 260, x: 100 + i, y: 200, toJSON() {} } as DOMRect
  })
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { vi.restoreAllMocks() })

/** A stand-in editor: every target the guided run points at, and the controls the host wires to `notify`. */
function Host({ tour, at, onProgress }: { tour: Tour; at?: number; onProgress?: (p: TourProgress) => void }) {
  return (
    <TourProvider onProgress={onProgress}>
      <Page tour={tour} at={at} />
      <TourLayer />
    </TourProvider>
  )
}
function Page({ tour, at }: { tour: Tour; at?: number }) {
  const t = useTour()
  return (
    <div>
      <button type="button" onClick={() => t.start(tour, at)}>Open tour</button>
      <div data-tour="transcript-row">Get 20% off today only.</div>
      <div data-tour="composer"><textarea aria-label="Describe a change" defaultValue="Make the offer 30% off" /><button type="button" data-tour-action="composer" onClick={() => t.notify('turn-started')}>Send</button></div>
      <div data-tour="trace">Trace</div>
      <div data-tour="gate"><button type="button" data-tour-action="gate" onClick={() => t.notify('take-ready')}>Go ahead</button></div>
      <div data-tour="proposal-row"><button type="button" data-tour-action="proposal-row" onClick={() => t.notify('heard-and-original')}>Hear it</button></div>
      <div data-tour="playback-switch">Edited · With proposals · As shot</div>
      <button type="button" data-tour="add-it" onClick={() => t.notify('added')}>Add it</button>
      <a href="#v/p1/export" data-tour="export" onClick={(e) => { e.preventDefault(); t.notify('export-opened') }}>Export</a>
      <button type="button" onClick={() => t.fail()}>Break it</button>
      <span data-testid="phase">{t.phase ?? 'off'}</span>
    </div>
  )
}

const coach = () => screen.getByRole('dialog', { name: /Tutorial step/ })

describe('the tour engine', () => {
  it('runs the guided run from the welcome card through its seven steps to the done card, reporting progress', async () => {
    const progress: TourProgress[] = []
    render(<Host tour={guidedRun} onProgress={(p) => progress.push(p)} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open tour' }))
    const welcome = screen.getByRole('dialog', { name: 'Welcome' })
    expect(welcome).toHaveTextContent('Change what a video says.')
    expect(screen.getByRole('button', { name: /Start the tour/ })).toHaveFocus()
    expect(progress.at(-1)).toEqual({ step: 0, finished: false, skipped: false })

    await userEvent.click(screen.getByRole('button', { name: /Start the tour/ }))
    expect(coach()).toHaveTextContent('Step 1 of 7')
    expect(coach()).toHaveTextContent('Voltage has read the clip')
    expect(screen.getByTestId('tour-ring')).toBeInTheDocument()
    expect(screen.getByTestId('tour-dim')).toBeInTheDocument()
    await waitFor(() => expect(within(coach()).getByRole('button', { name: 'Next' })).toHaveFocus())
    expect(progress.at(-1)).toEqual({ step: 1, finished: false, skipped: false })

    // Step 2 waits for the turn; the coach's Send presses the composer's own Send.
    await userEvent.click(within(coach()).getByRole('button', { name: 'Next' }))
    expect(coach()).toHaveTextContent('Step 2 of 7')
    expect(coach()).toHaveTextContent('→ Click Send')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Send' }))
    expect(coach()).toHaveTextContent('Step 3 of 7')

    // Step 3 has nothing to press: the action waits, and the step can be skipped.
    expect(within(coach()).getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(within(coach()).getByRole('button', { name: 'Skip this step' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))  // a stray event is ignored
    expect(coach()).toHaveTextContent('Step 3 of 7')
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead' })) // not what this step waits for either
    expect(coach()).toHaveTextContent('Step 3 of 7')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Skip this step' }))
    expect(coach()).toHaveTextContent('Step 4 of 7')

    await userEvent.click(within(coach()).getByRole('button', { name: 'Go ahead' }))
    expect(coach()).toHaveTextContent('Step 5 of 7')
    expect(coach()).toHaveTextContent('Hear it in the video, then without it')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Hear it' }))
    expect(coach()).toHaveTextContent('Step 6 of 7')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Add it' }))
    expect(coach()).toHaveTextContent('Step 7 of 7')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Export' }))

    const done = screen.getByRole('dialog', { name: 'Tour finished' })
    expect(done).toHaveTextContent('You changed what a video says.')
    expect(screen.getByRole('link', { name: 'Upload a video' })).toHaveAttribute('href', '#home')
    expect(progress.at(-1)).toEqual({ step: 8, finished: true, skipped: false })
    await userEvent.click(screen.getByRole('link', { name: 'Upload a video' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('says each step aloud, goes Back, and Escape skips with a toast that can replay', async () => {
    render(<Host tour={guidedRun} at={1} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open tour' }))
    expect(coach()).toHaveTextContent('Step 2 of 7')
    const live = screen.getAllByRole('status').find((el) => el.textContent?.startsWith('Step 2 of 7'))
    expect(live).toHaveTextContent('Tell Voltage what the video should say')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Back' }))
    expect(coach()).toHaveTextContent('Step 1 of 7')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('dialog', { name: 'Welcome' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const toast = screen.getByRole('status', { name: '' })
    expect(toast).toHaveTextContent('Tour skipped. Replay it any time from Help.')
    expect(screen.getByTestId('phase')).toHaveTextContent('skipped')
    await userEvent.click(screen.getByRole('button', { name: 'Replay now' }))
    expect(screen.getByRole('dialog', { name: 'Welcome' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.getByTestId('phase')).toHaveTextContent('off')
  })

  it('offers Skip this step when the host says the step failed, and gives focus back when it ends', async () => {
    render(<Host tour={showMe.add} />)
    const open = screen.getByRole('button', { name: 'Open tour' })
    await userEvent.click(open)
    expect(coach()).toHaveTextContent('Step 1 of 2')
    expect(screen.queryByRole('button', { name: 'Skip this step' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Break it' }))
    expect(within(coach()).getByRole('alert')).toHaveTextContent('did not finish')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Skip this step' }))
    expect(coach()).toHaveTextContent('Step 2 of 2')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Skip tour' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(open).toHaveFocus())
  })

  it('ends quietly after the last step of a short tour, which is not remembered', async () => {
    const onProgress = vi.fn()
    render(<Host tour={showMe.goal} onProgress={onProgress} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open tour' }))
    await userEvent.click(within(coach()).getByRole('button', { name: 'Send' }))
    expect(coach()).toHaveTextContent('Step 2 of 2')
    await userEvent.click(within(coach()).getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onProgress).not.toHaveBeenCalled()
  })

  it('covers the union of several targets, and draws no ring when none is on the page', () => {
    render(<div><div data-tour="a">a</div><div data-tour="bcd">b</div></div>)
    expect(measure(['a', 'bcd'], 0)).toEqual({ left: 101, top: 200, width: 302, height: 60 })
    expect(measure(['a'], 6)).toEqual({ left: 95, top: 194, width: 312, height: 72 })
    expect(measure(['zz'])).toBeNull()
  })

  it('is a no-op without a provider', () => {
    function Bare() { const t = useTour(); return <button type="button" onClick={() => t.start(guidedRun)}>{t.phase ?? 'off'}</button> }
    render(<><Bare /><TourLayer /></>)
    act(() => { screen.getByRole('button').click() })
    expect(screen.getByRole('button')).toHaveTextContent('off')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
