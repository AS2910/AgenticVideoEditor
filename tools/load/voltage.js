// The launch rehearsal's load test (rehearsal item 3). One iteration is one
// real session of a new user against a rehearsal stack (mocked vendors that
// wait like the real ones): sign in, Home, upload, a turn that proposes a
// line, the go-ahead that voices it, add it (renders), export.
//   k6 run -e BASE=http://localhost:8090 -e USERS=tools/load/users.json tools/load/voltage.js
import http from 'k6/http'
import { check, sleep } from 'k6'
import { Trend, Counter } from 'k6/metrics'

const BASE = (__ENV.BASE || 'http://localhost:8090') + '/api'
const USERS = JSON.parse(open(__ENV.USERS || './users.json'))
const CLIP = open(__ENV.CLIP || '../../frontend/public/sample-ad.mp4', 'b')
const H = { 'X-Requested-With': 'voltage', 'Content-Type': 'application/json' }
const PEAK = Number(__ENV.PEAK || 50)
const NAMES = ['POST /auth/password/login', 'GET /auth/me', 'GET /me/flags', 'GET /videos', 'GET /projects', 'POST /videos (upload)',
  'GET /videos/{id}', 'GET /videos/{id}/messages', 'POST /videos/{id}/turns', 'GET /jobs/{id}', 'GET /videos/{id}/jobs',
  'POST /plans/{id}/approve (renders)', 'POST /videos/{id}/export', 'GET /billing']

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus', startVUs: 0,
      stages: [
        { duration: __ENV.RAMP || '4m', target: PEAK },
        { duration: __ENV.HOLD || '6m', target: PEAK },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '3m', gracefulStop: '3m',
    },
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'max', 'count'],
  // A threshold per call makes k6 report each call's own p50/p95 (always true; nothing is gated here).
  thresholds: Object.fromEntries(NAMES.map((n) => [`http_req_duration{name:${n}}`, ['max>=0']])),
}

const turnTotal = new Trend('turn_total_ms', true)      // POST /turns until the job is done
const voiceTotal = new Trend('voice_turn_total_ms', true)
const failedJobs = new Counter('jobs_failed')
const queueWait = new Trend('turn_queue_wait_ms', true)   // POST /turns until the job leaves "queued" (2 s polls)

function tag(name) { return { tags: { name } } }

function waitJob(jobId, trend, started) {
  let queued = true
  for (let i = 0; i < 300; i++) {
    const r = http.get(`${BASE}/jobs/${jobId}`, tag('GET /jobs/{id}'))
    const s = r.status === 200 ? r.json('status') : null
    if (queued && s && s !== 'queued') { queued = false; queueWait.add(Date.now() - started) }
    if (s === 'succeeded' || s === 'failed' || s === 'cancelled') {
      trend.add(Date.now() - started)
      if (s !== 'succeeded') failedJobs.add(1)
      return r
    }
    sleep(2)
  }
  failedJobs.add(1)
  return null
}

export default function () {
  const u = USERS[(__VU - 1) % USERS.length]
  const jar = http.cookieJar()
  jar.clear(BASE)
  let r = http.post(`${BASE}/auth/password/login`, JSON.stringify({ email: u.email, password: u.password }), { headers: H, ...tag('POST /auth/password/login') })
  if (!check(r, { 'signed in': (x) => x.status === 200 })) { sleep(5); return }
  http.get(`${BASE}/auth/me`, tag('GET /auth/me'))
  http.get(`${BASE}/me/flags`, tag('GET /me/flags'))
  http.get(`${BASE}/videos`, tag('GET /videos'))
  http.get(`${BASE}/projects`, tag('GET /projects'))
  sleep(2 + Math.random() * 3)

  r = http.post(`${BASE}/videos`, { file: http.file(CLIP, 'sample-ad.mp4', 'video/mp4'), consent: 'true' },
    { headers: { 'X-Requested-With': 'voltage' }, timeout: '180s', ...tag('POST /videos (upload)') })
  if (!check(r, { 'uploaded': (x) => x.status === 200 })) { sleep(5); return }
  const v = r.json('video_id')
  http.get(`${BASE}/videos/${v}`, tag('GET /videos/{id}'))
  http.get(`${BASE}/videos/${v}/messages?after=0`, tag('GET /videos/{id}/messages'))
  sleep(3 + Math.random() * 4)

  let t0 = Date.now()
  r = http.post(`${BASE}/videos/${v}/turns`, JSON.stringify({ text: 'Add a short line at the start' }), { headers: H, ...tag('POST /videos/{id}/turns') })
  if (!check(r, { 'turn started': (x) => x.status === 200 || x.status === 202 })) { sleep(5); return }
  waitJob(r.json('job_id'), turnTotal, t0)
  sleep(2 + Math.random() * 3)

  t0 = Date.now()
  r = http.post(`${BASE}/videos/${v}/turns`, JSON.stringify({ text: 'Go ahead', approve: true }), { headers: H, ...tag('POST /videos/{id}/turns') })
  if (!check(r, { 'go-ahead started': (x) => x.status === 200 || x.status === 202 })) { sleep(5); return }
  const done = waitJob(r.json('job_id'), voiceTotal, t0)
  const plan = done && done.json('result.plan')
  const items = plan && plan.items ? plan.items.filter((i) => i.status === 'ready').map((i) => i.item_id) : []
  http.get(`${BASE}/videos/${v}/jobs?active=1`, tag('GET /videos/{id}/jobs'))
  sleep(3 + Math.random() * 4)

  if (items.length) {
    r = http.post(`${BASE}/videos/${v}/plans/${plan.plan_id}/approve`, JSON.stringify({ items }), { headers: H, timeout: '300s', ...tag('POST /plans/{id}/approve (renders)') })
    check(r, { 'added': (x) => x.status === 200 })   // run 4, item 3a: answers at once with the render's job
    sleep(2 + Math.random() * 3)
    r = http.post(`${BASE}/videos/${v}/export`, JSON.stringify({ purpose: 'export' }), { headers: H, timeout: '300s', ...tag('POST /videos/{id}/export') })
    check(r, { 'exported': (x) => x.status === 200 || x.status === 202 })   // run 4, item 3d: 202 is its render job
  }
  http.get(`${BASE}/billing`, tag('GET /billing'))
  sleep(5 + Math.random() * 5)
}
