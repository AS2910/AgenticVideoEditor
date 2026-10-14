import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'
const KEY = 'voltage-theme'

const systemDark = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches

/** The saved choice; storage can be blocked or empty, and then the system decides. */
export function readTheme(): Theme {
  try {
    const v = window.localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme): void {
  const dark = theme === 'dark' || (theme === 'system' && systemDark())
  document.documentElement.classList.toggle('dark', dark)
}

/** Light, dark, or follow the system. The first paint is set by the inline
 *  script in index.html, so there is no flash; this keeps it in step after. */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme)
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => applyTheme('system')
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [theme])
  const setTheme = useCallback((t: Theme) => {
    try {
      if (t === 'system') window.localStorage.removeItem(KEY)
      else window.localStorage.setItem(KEY, t)
    } catch {
      /* the choice just lasts this visit */
    }
    setThemeState(t)
  }, [])
  return [theme, setTheme]
}
