/**
 * The design system's contract, checked against the stylesheets themselves
 * (UX-6, R-1). jsdom does not resolve the cascade, so these read the CSS
 * as text: what the rules forbid is spelled out and easy to grep for.
 */
import { describe, it, expect } from 'vitest'

// Every stylesheet, as text, through Vite: jsdom does not resolve the cascade,
// so the rules below read the CSS itself, and what they forbid is easy to grep for.
const raw = import.meta.glob(['../App.module.css', '../components/*.css', './theme.css'], {
  query: '?raw', import: 'default', eager: true,
}) as Record<string, string>
const sheets = Object.keys(raw).filter((k) => !k.endsWith('theme.css'))
const read = (p: string): string => raw[p]
const name = (p: string) => p.replace(/^\.\.\//, '')
const themeCss = raw['./theme.css']

/** Every `selector { declarations }` block in a sheet, flattened out of media queries. */
function blocks(css: string): { selector: string; body: string }[] {
  const out: { selector: string; body: string }[] = []
  const re = /([^{}]+)\{([^{}]*)\}/g
  let m: RegExpExecArray | null
  css = css.replace(/\/\*[\s\S]*?\*\//g, '')
  while ((m = re.exec(css))) {
    const selector = m[1].trim()
    if (selector.startsWith('@media') || selector.startsWith('@keyframes') || /^\d+%|^from$|^to$/.test(selector)) continue
    out.push({ selector, body: m[2] })
  }
  return out
}

describe('the design system, as the stylesheets keep it', () => {
  it('spells no colour in a component — every colour is a token from theme.css', () => {
    const offenders = sheets.flatMap((p) =>
      read(p).split('\n').map((l, i) => ({ p, i, l })).filter(({ l }) => /#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(l)),
    )
    expect(offenders.map(({ p, i, l }) => `${name(p)}:${i + 1} ${l.trim()}`)).toEqual([])
  })

  it('never removes a focus outline without a visible replacement in the same block', () => {
    const offenders: string[] = []
    for (const p of sheets) {
      for (const { selector, body } of blocks(read(p))) {
        if (!/outline:\s*(none|0)/.test(body)) continue
        // A block that drops the outline must put a ring back: a box-shadow of
        // its own, or sit on an element whose container draws the ring
        // (the chat composer, the strip's composer and the goal card, which are listed here on purpose).
        const replaced = /box-shadow/.test(body)
        const containerRing = /\.(input|railInput):focus$/.test(selector) && /composer:focus-within|card:focus-within|railComposer:focus-within/.test(read(p))
        if (!replaced && !containerRing) offenders.push(`${name(p)} ${selector}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('sets no text under 12px', () => {
    const offenders = sheets.flatMap((p) =>
      [...read(p).matchAll(/font-size:\s*([\d.]+)px/g)].filter((m) => parseFloat(m[1]) < 12).map((m) => `${name(p)} ${m[0]}`),
    )
    expect(offenders).toEqual([])
  })

  it('uses --faint only where the design system allows it: glyphs, dividers, and a label beside larger text', () => {
    // The classes allowed to be faint. Anything else in --faint is a sentence,
    // a time or a cost that someone must read, and belongs in --muted.
    const allowed = new Set(['.grip', '.slash', '.tick'])  // .tick: a 1px word mark on the monitor's timeline (UX-7b)
    const offenders: string[] = []
    for (const p of sheets) {
      for (const { selector, body } of blocks(read(p))) {
        if (!/var\(--faint\)/.test(body)) continue
        if (!selector.split(',').every((s) => allowed.has(s.trim().split(/[:\s[]/)[0]))) offenders.push(`${name(p)} ${selector}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('gives every chip, pill and inline action the 36px floor, and leaves the 44px floor to theme.css', () => {
    const theme = themeCss
    expect(theme).toMatch(/button, select, textarea, input[^{]*\{\s*min-height: var\(--target\)/)
    // A chip-shaped control that sets its own small vertical padding (1–9px)
    // has opted out of the 44px floor and must say how tall it is instead.
    const chipLike = /\.(pill|pillOn|option|optionOn|chip|choice|choiceOn|example|on|off|version|versionOn|precise|preciseOn|action|stop|confirm|detect|zoom button)\b/
    const offenders: string[] = []
    for (const p of sheets) {
      for (const { selector, body } of blocks(read(p))) {
        if (!chipLike.test(selector) || /min-height/.test(body)) continue
        const pad = body.match(/padding:\s*([\d.]+)px/)
        if (!pad) continue
        const vertical = parseFloat(pad[1])
        if (vertical < 1 || vertical > 9) continue
        // The status chip in LineDoc is not interactive; everything else that looks like a chip is.
        if (name(p) === 'components/LineDoc.module.css' && /^\.chip\b/.test(selector)) continue
        offenders.push(`${name(p)} ${selector}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('animates fills with transform, never width', () => {
    const offenders = sheets.flatMap((p) =>
      [...read(p).matchAll(/transition:[^;]*\b(width|height|left|top)\b[^;]*;/g)].map((m) => `${name(p)} ${m[0]}`),
    )
    expect(offenders).toEqual([])
  })

  it('uses dvh, not vh, for full-height screens', () => {
    const offenders = sheets.flatMap((p) => [...read(p).matchAll(/\b(min-)?height:\s*100vh/g)].map((m) => `${name(p)} ${m[0]}`))
    expect(offenders).toEqual([])
  })
})
