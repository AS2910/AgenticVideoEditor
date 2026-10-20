# Editor shell and the stale question card (2026-10-20)

## Evidence: what fixed the height (measured before changing anything)

Measured in Chrome (Playwright) on p61, at 1440x900, 1512x860 and 1280x720, on the live app and on a copy of the data:

| Element | Box | Content | Scrolls |
|---|---|---|---|
| html / body | 900 | 900 | no (overflow visible, not locked) |
| editor root `div.flex.h-dvh` | 900 | 900 | no |
| `main` (the whole left column) | 838 | 1695 to 1823 | yes, as one scroller |
| Voltage pane root `aside.pane-root` | 838 | 917 | **yes, by 79 px**: `overflow-x: hidden` makes overflow-y compute to auto |

- No `100vh` / `calc(100vh - X)` and no height measured once in JS were found (searched every page and component).
- The pane root was a hidden scroll box: the composer block overhangs it by 79 px (106 px at 1280x720), so anything scrolled into view in the pane (focus, an autoscroll) could move the pane's own header up out of view and leave a gap below.
- html and body were not locked, so any overflow of the shell becomes a page scroll; the left column was one scroller with no inner list, so the transcript's rows were cut by the column's edge.
- The page-level scroll itself (the app header leaving the view) did not reproduce in headless Chrome at rest or after focus, clicks, arrow keys, opening Tracks or wheel scrolls.

## Fix

- The shell is a `100dvh` grid, `[header auto][main minmax(0,1fr)]`, overflow hidden; html and body are locked while the editor is on screen (desktop). Phone width: block layout, the page scrolls, the header is sticky.
- `.pane-root` uses `overflow: clip` (no scroll box); the thread is the pane's only scroller.
- The transcript rows scroll in their own list under the pinned header; its height is the space left in the column below the header (at least 320 px), measured by a ResizeObserver on the column, the header and the column's content. Rows never shrink (`[&>*]:shrink-0`).
- `overscroll-behavior: contain` on the list; Shift+wheel over it scrolls the column; keyboard focus scrolls only the list; "line N" in Voltage's words scrolls the list to the row and flashes it. Slim themed scrollbars (8 px, 12 px on hover).
- Layout tests: `npm run test:layout` (Playwright, the installed Chrome, API mocked, 30 lines).

## The stale question card

A waiting question resolves when its subject changes outside the chat: lines added or discarded in the editor (`_resolve_question`, kept with `resolved: {why, by, at}`), or a newer turn starting (kept in `settings.last_question`). A resolved question is never a gate for the next turn. The card turns quiet: "Answered in the editor: you added all four lines.", options disabled.
