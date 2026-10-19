#!/usr/bin/env node
/* Visual test of the Voltage pane in real layout (pane-render, 2026-10-20).
 *
 * jsdom has no layout, so this runs headless Chrome over the DevTools
 * Protocol against a Vite server for visual/pane.html. At pane widths 320,
 * 390 and 440 px, and with the header in every status, it asserts:
 *   - the pane never scrolls sideways (scrollWidth equals clientWidth, for the
 *     pane and for the thread) and nothing in it sits outside its edges;
 *   - no option text is clipped (each option's words inside its button, each
 *     button inside the card, nothing overflowing the button);
 *   - the header is one line (wave, name, status and info on one row; the
 *     status never breaks onto a second line);
 *   - the 60-character file name in a step line wraps inside the trace;
 *   - below 380 px the context chips fold behind "Context".
 *
 *   node visual/pane.visual.mjs [--out <dir>] [--port 5175] [--cdp-port 9347] [--chrome <path>]
 *
 * Writes a screenshot per width to --out (default: the OS temp dir) and exits
 * non-zero when any check fails. */
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : fallback
}
const out = resolve(arg('out', join(tmpdir(), 'voltage-pane-visual')))
const port = Number(arg('port', 5175))
const cdpPort = Number(arg('cdp-port', 9347))
const chromePath = arg('chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
const WIDTHS = [320, 390, 440]
const STATUSES = ['ready', 'working', 'reading', '3 proposed', 'standing by', 'needs your go']
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** What the page measures: run inside it. */
function measure() {
  const r = (e) => e.getBoundingClientRect()
  const pane = document.querySelector('[data-testid=voltage-pane]')
  const log = pane.querySelector('[role=log]')
  const header = pane.querySelector('[data-testid=pane-header]')
  const status = pane.querySelector('[data-testid=pane-status]')
  const P = r(pane)
  const name = (e) => `${e.tagName.toLowerCase()}${e.dataset.testid ? `[${e.dataset.testid}]` : ''}.${[...e.classList].slice(0, 3).join('.')}`
  const outside = [...pane.querySelectorAll('*')]
    .filter((e) => { const b = r(e); return b.width > 0 && b.height > 0 && (b.right > P.right + 0.5 || b.left < P.left - 0.5) })
    .map(name)
  const card = pane.querySelector('[data-testid=clarify]')
  const C = r(card)
  const options = [...card.querySelectorAll('button.opt')].map((b) => {
    const B = r(b)
    const range = document.createRange()
    range.selectNodeContents(b)
    const rects = [...range.getClientRects()].filter((x) => x.width > 0)
    const textOut = rects.filter((x) => x.right > B.right + 0.5 || x.left < B.left - 0.5 || x.bottom > B.bottom + 0.5 || x.top < B.top - 0.5).length
    return {
      label: b.querySelector('[data-testid=option-label]').textContent,
      width: Math.round(B.width), height: Math.round(B.height),
      overflowX: b.scrollWidth - b.clientWidth, overflowY: b.scrollHeight - b.clientHeight,
      inCard: B.left >= C.left - 0.5 && B.right <= C.right + 0.5,
      textOutside: textOut,
      lines: Math.round((r(b.querySelector('[data-testid=option-label]')).height) / parseFloat(getComputedStyle(b).lineHeight)),
    }
  })
  const kids = [...header.children].map((e) => r(e)).filter((b) => b.width > 0)
  const mids = kids.map((b) => b.top + b.height / 2)
  const lh = parseFloat(getComputedStyle(status).lineHeight) || 18
  const step = [...pane.querySelectorAll('.trace .ln')].find((e) => e.textContent.includes('.mp4'))
  const trace = step.closest('[data-testid=trace]')
  const toggle = pane.querySelector('[data-testid=context-toggle]')
  const chips = [...pane.querySelectorAll('[data-testid=context-chip]')]
  return {
    pane: { width: Math.round(P.width), scrollWidth: pane.scrollWidth, clientWidth: pane.clientWidth },
    thread: { scrollWidth: log.scrollWidth, clientWidth: log.clientWidth },
    doc: { scrollWidth: document.documentElement.scrollWidth, innerWidth: innerWidth },
    outside,
    options,
    header: {
      height: Math.round(r(header).height),
      rowSpread: Math.round(Math.max(...mids) - Math.min(...mids)),
      statusHeight: Math.round(r(status).height), statusLineHeight: lh,
      statusTruncated: status.scrollWidth > status.clientWidth,
      nameHeight: Math.round(r(header.querySelector('h2')).height),
    },
    step: { overflowX: step.scrollWidth - step.clientWidth, inTrace: r(step).right <= r(trace).right + 0.5, height: Math.round(r(step).height) },
    context: { toggleShown: toggle ? r(toggle).width > 0 : false, chipsShown: chips.filter((c) => r(c).width > 0).length },
  }
}

async function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl)
  await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no })
  let id = 0
  const waiting = new Map()
  const listeners = []
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data)
    if (msg.id && waiting.has(msg.id)) {
      const { ok, no } = waiting.get(msg.id)
      waiting.delete(msg.id)
      if (msg.error) no(new Error(msg.error.message)); else ok(msg.result)
    } else if (msg.method) listeners.forEach((l) => l(msg))
  }
  const send = (method, params = {}) => new Promise((ok, no) => { const n = ++id; waiting.set(n, { ok, no }); ws.send(JSON.stringify({ id: n, method, params })) })
  const once = (method) => new Promise((ok) => { const l = (m) => { if (m.method === method) { listeners.splice(listeners.indexOf(l), 1); ok(m.params) } }; listeners.push(l) })
  return { send, once, close: () => ws.close() }
}

async function main() {
  mkdirSync(out, { recursive: true })
  // Another Chrome on the debugging port would be driven instead of ours.
  if (await fetch(`http://127.0.0.1:${cdpPort}/json/version`).then(() => true, () => false)) {
    throw new Error(`Port ${cdpPort} already has a Chrome on it; pass --cdp-port <free port>.`)
  }
  const server = await createServer({ root, configFile: join(root, 'vite.config.ts'), server: { host: '127.0.0.1', port, strictPort: true, fs: { allow: [root, realpathSync(join(root, 'node_modules'))] } }, logLevel: 'error' })
  await server.listen()
  const profile = mkdtempSync(join(tmpdir(), 'pane-chrome-'))
  const chrome = spawn(chromePath, ['--headless=new', `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', 'about:blank'], { stdio: 'ignore' })
  const failures = []
  const results = []
  try {
    let page = null
    for (let i = 0; i < 50 && !page; i++) {
      try {
        const res = await fetch(`http://127.0.0.1:${cdpPort}/json/new?about:blank`, { method: 'PUT' })
        page = await res.json()
      } catch { await sleep(200) }
    }
    if (!page) throw new Error('Chrome did not start')
    const c = await cdp(page.webSocketDebuggerUrl)
    await c.send('Page.enable')
    await c.send('Runtime.enable')
    await c.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: 'dark' }] })
    for (const w of WIDTHS) {
      await c.send('Emulation.setDeviceMetricsOverride', { width: w, height: 800, deviceScaleFactor: 2, mobile: false })
      for (const status of STATUSES) {
        const loaded = c.once('Page.loadEventFired')
        await c.send('Page.navigate', { url: `http://127.0.0.1:${port}/visual/pane.html?w=${w}&status=${encodeURIComponent(status)}` })
        await loaded
        await c.send('Runtime.evaluate', { expression: 'new Promise((r, no) => { const end = Date.now() + 15000; const t = () => document.querySelector("[data-testid=clarify]") ? document.fonts.ready.then(() => setTimeout(r, 400)) : Date.now() > end ? no(new Error("the pane did not render: " + location.href)) : setTimeout(t, 50); t() })', awaitPromise: true })
        const { result } = await c.send('Runtime.evaluate', { expression: `(${measure.toString()})()`, returnByValue: true })
        const m = result.value
        const fail = (why) => failures.push(`${w}px / ${status}: ${why}`)
        if (m.pane.scrollWidth !== m.pane.clientWidth) fail(`pane scrolls sideways (${m.pane.scrollWidth} vs ${m.pane.clientWidth})`)
        if (m.thread.scrollWidth !== m.thread.clientWidth) fail(`thread scrolls sideways (${m.thread.scrollWidth} vs ${m.thread.clientWidth})`)
        if (m.doc.scrollWidth > m.doc.innerWidth) fail(`page scrolls sideways (${m.doc.scrollWidth} vs ${m.doc.innerWidth})`)
        if (m.outside.length) fail(`outside the pane: ${m.outside.slice(0, 5).join(', ')}`)
        for (const o of m.options) {
          if (o.overflowX > 0 || o.overflowY > 0 || o.textOutside || !o.inCard) fail(`option clipped: ${o.label} ${JSON.stringify(o)}`)
        }
        if (m.header.rowSpread > 2) fail(`header is not one row (spread ${m.header.rowSpread}px)`)
        if (m.header.statusHeight > m.header.statusLineHeight * 1.5) fail(`status wraps (${m.header.statusHeight}px)`)
        if (m.header.nameHeight > 32) fail(`name wraps (${m.header.nameHeight}px)`)
        if (m.step.overflowX > 0 || !m.step.inTrace) fail(`file name step overflows ${JSON.stringify(m.step)}`)
        if (w < 380 ? (!m.context.toggleShown || m.context.chipsShown !== 0) : (m.context.toggleShown || m.context.chipsShown !== 2)) fail(`context chips ${JSON.stringify(m.context)}`)
        results.push({ width: w, status, ...m })
        if (status === 'needs your go') {
          const shot = await c.send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: w, height: 760, scale: 1 } })
          writeFileSync(join(out, `pane-${w}.png`), Buffer.from(shot.data, 'base64'))
        }
      }
    }
    c.close()
  } finally {
    chrome.kill()
    await server.close()
    await sleep(300)
    rmSync(profile, { recursive: true, force: true })
  }
  writeFileSync(join(out, 'results.json'), JSON.stringify(results, null, 2))
  for (const w of WIDTHS) {
    const rows = results.filter((x) => x.width === w)
    const go = rows.find((x) => x.status === 'needs your go')
    console.log(`${w}px  pane ${go.pane.scrollWidth}/${go.pane.clientWidth}  thread ${go.thread.scrollWidth}/${go.thread.clientWidth}  ` +
      `header ${go.header.height}px (row spread max ${Math.max(...rows.map((x) => x.header.rowSpread))}px, status ${go.header.statusHeight}px${go.header.statusTruncated ? ', truncated' : ''})  ` +
      `options ${go.options.map((o) => `${o.width}x${o.height}`).join(' ')}  clipped ${go.options.filter((o) => o.overflowX > 0 || o.overflowY > 0 || o.textOutside).length}  ` +
      `context ${go.context.toggleShown ? 'folded' : `${go.context.chipsShown} chips`}`)
  }
  console.log(`screenshots and results.json in ${out}`)
  if (failures.length) {
    console.error(`\n${failures.length} failed:\n${failures.join('\n')}`)
    process.exit(1)
  }
  console.log(`all checks passed at ${WIDTHS.join(', ')} px in ${STATUSES.length} statuses`)
}

main().catch((e) => { console.error(e); process.exit(1) })
