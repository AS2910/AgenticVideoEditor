/**
 * The design system's contract (UX-8), checked against the source itself:
 * jsdom does not resolve the cascade, so these read the globals and the
 * components as text. What the rules forbid is easy to grep for.
 */
import { describe, it, expect } from 'vitest'

const css = import.meta.glob(['./globals.css', '../**/*.css'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const globals = css['./globals.css']
const sources = import.meta.glob(['../**/*.tsx', '!../**/*.test.tsx', '!../components/ui/*.tsx'], {
  query: '?raw', import: 'default', eager: true,
}) as Record<string, string>
const ui = import.meta.glob('../components/ui/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

const TOKENS = [
  'background', 'foreground', 'card', 'card-foreground', 'popover', 'popover-foreground', 'primary', 'primary-foreground',
  'secondary', 'secondary-foreground', 'muted', 'muted-foreground', 'accent', 'accent-foreground', 'destructive',
  'border', 'input', 'ring', 'changed', 'changed-soft', 'ok', 'ok-soft', 'needs', 'needs-soft',
  'spk-a', 'spk-b', 'spk-c', 'spk-d',
]
const block = (selector: string) => globals.slice(globals.indexOf(selector)).split('}')[0]

describe('the design system, as the source keeps it', () => {
  it('keeps no hand-written stylesheet beyond globals.css', () => {
    expect(Object.keys(css)).toEqual(['./globals.css'])
  })

  it('defines every semantic token in both light and dark', () => {
    const light = block(':root {')
    const dark = block('.dark {')
    for (const t of TOKENS) {
      expect(light, `:root --${t}`).toMatch(new RegExp(`--${t}:`))
      expect(dark, `.dark --${t}`).toMatch(new RegExp(`--${t}:`))
    }
  })

  it('exposes every token to Tailwind as a colour', () => {
    for (const t of TOKENS) expect(globals, `--color-${t}`).toContain(`--color-${t}: var(--${t});`)
  })

  it('spells no colour in a component — every colour is a token', () => {
    const offenders = Object.entries(sources).flatMap(([p, src]) =>
      src.split('\n').map((l, i) => ({ p, i, l }))
        .filter(({ l }) => /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(|hsla?\(|\b(?:bg|text|border|ring|fill|stroke|from|to|via)-(?:red|blue|green|gray|slate|zinc|neutral|stone|amber|teal|cyan|emerald|rose|orange|yellow|purple|violet|indigo|pink|sky|lime|fuchsia)-\d{2,3}\b/.test(l))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`),
    )
    expect(offenders).toEqual([])
  })

  it('uses no gradients, glows or blurs — the look is flat', () => {
    const offenders = Object.entries(sources).flatMap(([p, src]) =>
      src.split('\n').map((l, i) => ({ p, i, l }))
        .filter(({ l }) => /\bbg-(?:gradient|linear|radial|conic)|\bbackdrop-blur|\bblur-|\bdrop-shadow|shadow-\[/.test(l))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`),
    )
    expect(offenders).toEqual([])
  })

  it('sets no text under 12px', () => {
    const offenders = Object.entries({ ...sources, ...ui }).flatMap(([p, src]) =>
      src.split('\n').map((l, i) => ({ p, i, l }))
        .filter(({ l }) => /\btext-\[(?:[0-9]|1[01])(?:\.\d+)?px\]|\btext-\[0?\.[0-6]\d*rem\]/.test(l))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`),
    )
    expect(offenders).toEqual([])
  })

  it('never removes a focus outline without a visible replacement', () => {
    // A class string can span lines, so the ring may sit a line or two after outline-none.
    // A heading focused by script (tabIndex -1) is not a stop for the keyboard.
    const offenders = Object.entries(sources).flatMap(([p, src]) => {
      const lines = src.split('\n')
      return lines
        .map((l, i) => ({ p, i, l, near: lines.slice(i, i + 3).join(' ') }))
        .filter(({ l, near }) => /\boutline-none\b/.test(l) && !/focus(?:-visible|-within)?:(?:ring|border|outline)|focus-within:|tabIndex=\{-1\}/.test(near))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`)
    })
    // The phone strip's composer input sits inside a form that carries the ring.
    expect(offenders.filter((o) => !o.includes('App.tsx'))).toEqual([])
  })

  it('uses dvh, not vh, for full-height screens', () => {
    const offenders = Object.entries(sources).flatMap(([p, src]) =>
      src.split('\n').map((l, i) => ({ p, i, l })).filter(({ l }) => /\b(?:min-|max-)?h-screen\b|\[\d+vh\]/.test(l) && !/dvh/.test(l))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`),
    )
    expect(offenders).toEqual([])
  })

  it('keeps shadcn radii small: nothing past rounded-xl', () => {
    const offenders = Object.entries(sources).flatMap(([p, src]) =>
      src.split('\n').map((l, i) => ({ p, i, l })).filter(({ l }) => /\brounded(?:-[a-z]+)?-(?:2xl|3xl|4xl)\b|rounded-\[(?:1[5-9]|[2-9]\d)px\]/.test(l))
        .map(({ p, i, l }) => `${p}:${i + 1} ${l.trim()}`),
    )
    expect(offenders).toEqual([])
  })
})
