import { useEffect } from 'react'
import type { RefObject } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * What a sheet owes the keyboard (UX-6, R-2): focus moves into it when it
 * opens, Tab stays inside it, Escape closes it, and focus goes back to
 * whatever opened it when it closes. `onClose` is what Escape does.
 */
export function useModal(sheet: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    const el = sheet.current
    if (!el) return
    const opener = document.activeElement as HTMLElement | null
    const focusables = () => Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
    // The title first, so the sheet is announced; else the first control.
    const heading = el.querySelector<HTMLElement>('h1, h2, [data-autofocus]')
    if (heading) {
      heading.tabIndex = -1
      heading.focus()
    } else {
      focusables()[0]?.focus()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !el.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (active === last || !el.contains(active))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus?.()
    }
    // The sheet mounts once; what Escape does is read fresh through the ref below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheet])
}
