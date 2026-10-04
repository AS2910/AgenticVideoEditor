import '@testing-library/jest-dom/vitest'

// The upload goes through XMLHttpRequest so it can report progress (UX-6);
// the tests mock `fetch`, so this stand-in routes an XHR through fetch and
// fires one progress event, keeping the app's own upload code under test.
class FetchBackedXHR {
  status = 0
  responseText = ''
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  private method = 'GET'
  private url = ''
  private headers: Record<string, string> = {}
  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader(k: string, v: string) { this.headers[k] = v }
  send(body?: BodyInit | null) {
    this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 })
    Promise.resolve(fetch(this.url, { method: this.method, headers: this.headers, body }))
      .then(async (res) => {
        // The tests' fetch doubles are not always full Responses.
        this.status = res.status ?? (res.ok ? 200 : 500)
        const data = typeof res.json === 'function' ? await res.json().catch(() => undefined) : undefined
        this.responseText = data !== undefined ? JSON.stringify(data) : typeof res.text === 'function' ? await res.text() : ''
        this.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 2 })
        this.onload?.()
      })
      .catch(() => this.onerror?.())
  }
}
// @ts-expect-error — a test double for the browser's XMLHttpRequest
globalThis.XMLHttpRequest = FetchBackedXHR
