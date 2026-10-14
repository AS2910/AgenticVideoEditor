import { useEffect, useState } from 'react'

/** A sheet gives focus back to whatever opened it when it goes away. Radix's
 *  Dialog does this on a timer after close; this also covers a sheet that is
 *  unmounted outright (the app removes it from the tree), synchronously. The
 *  opener is read during the first render, before focus moves into the sheet. */
export function useReturnFocus() {
  const [opener] = useState(() => (typeof document === 'undefined' ? null : (document.activeElement as HTMLElement | null)))
  useEffect(() => () => { opener?.focus?.() }, [opener])
}
