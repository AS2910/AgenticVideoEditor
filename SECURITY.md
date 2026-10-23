# Security review (launch rehearsal, item 5, 23 Oct 2026)

What was checked before the public launch on 4 Nov 2026, how, what was found,
what was fixed (each fix has a test), and what is left. The earlier launch
night already added signed media URLs (`?mt=`), upload sniffing, rate limits,
CORS, security headers, the CSRF header on writes and production fail-fast;
those were re-checked here, not assumed.

Reporting a problem: write to the trust address (`AVE_TRUST_EMAIL`), or use the
abuse form on any share page.

## 1. Dependencies

**How.** `pip-audit` (run with `uvx`, not installed in the app's venv) over
`pip freeze` of the backend venv (67 packages); `npm audit` in `frontend/`.

| Finding | Severity | Where | Fix |
|---|---|---|---|
| certifi 2026.7.22 trusts the emSign roots whose intermediates were compromised (GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320) | critical | transitive (httpx) | `certifi>=2026.10.19` declared in `backend/pyproject.toml`; the dev venv upgraded to 2026.10.19 |
| vite 8.1.5: cross-origin script execution through custom middleware; files outside `server.fs.allow` served; launch-editor issues | high | dev server only | vite `^8.3.5` |
| @playwright/test / playwright 1.48.2: browsers downloaded without verifying TLS | high | dev only | `^1.64.1` |
| undici 7.28 (via jsdom): many, incl. TLS bypass in BalancedPool, cookie disclosure | high | tests only | resolved to 7.30.1 |
| nanoid 3.3.16 (loop when size is 0), source-map-js 1.2.1 (DoS) | high | build only | resolved to 3.3.20 / 1.2.2 |
| vitest 4.1.10 / @vitest/mocker: path traversal and code injection via the mock server | moderate | tests only | vitest `^4.1.12` |
| postcss 8.5.19: `sourceMappingURL` reads arbitrary `.map` files | moderate | build only | resolved to 8.5.31 |

After the fixes: `npm audit` 0 vulnerabilities; `pip-audit` 0 on the installed
set. None of the npm findings reached the shipped bundle: all were dev,
build or test tooling. Not audited: the optional extras (`postgres`, `room`,
`measure`: psycopg, pgserver, torch, demucs, transformers), which are not
installed in the dev venv; run `pip-audit` inside the production image after
`docker compose build`.

Note: `npm install` 10.9.3 crashes on this lockfile (`Cannot read properties of
null (reading 'edgesOut')`, an Arborist peer-set bug); the lockfile was
regenerated with `npx npm@11 install` (lockfileVersion 3, unchanged format).

## 2. SSRF on link import

**Before.** Only Google Drive and Dropbox links were accepted, but the
download followed redirects automatically (`follow_redirects=True`), so a
redirect from either (or from any open redirect on those hosts) could reach
`http://169.254.169.254/` (cloud metadata), `localhost`, or the private
network. No address checks at all; environment proxies honoured.

**Now** (`backend/app/linkimport.py`):

- `download` follows redirects itself (at most 5) and checks every hop with
  `check_url`: http/https only, ports 80/443 only, no credentials in the URL,
  no single-label or internal names (`localhost`, `metadata`,
  `metadata.google.internal`, `*.internal`, `*.local`, `*.localhost`, `.svc`
  ...), and no literal address that is not public.
- The real client (`safe_client()`) has a guarded network backend: each
  connection resolves the host once, refuses it if *any* answer is not public
  (`check_ip`), and connects to the address it checked. A DNS answer that
  changes between check and connect (rebinding) has nothing to change. TLS
  still uses the original host name for SNI and certificate checks (httpcore
  takes `server_hostname` from the URL, not the socket).
- `check_ip` refuses: RFC 1918, CGNAT 100.64/10, loopback, link-local
  (169.254/16 incl. metadata, fe80::/10), unique-local fc00::/7, site-local,
  multicast, reserved/benchmark/documentation ranges, 0.0.0.0/8 and `::`, and
  the IPv6 forms of IPv4 (IPv4-mapped `::ffff:`, IPv4-compatible, NAT64
  64:ff9b::/96, 6to4, Teredo), each judged as its IPv4 address. Numeric host
  forms (`2130706433`, `0x7f000001`) are refused before resolution.
- No proxies from the environment (`trust_env=False`): a proxy would connect
  for us and skip the check.

Tests: `backend/tests/security/test_ssrf.py` (71 cases, fake DNS and a fake
socket layer; nothing leaves the machine).

## 3. Application checks

### CSRF (fixed)

**Before.** The `X-Requested-With: voltage` check lived in `current_owner`,
so routes that read the session another way skipped it:
`POST /workspace/switch`, `POST /invites/{token}/accept` (a page elsewhere
could make a signed-in visitor join the attacker's workspace and switch them
into it, so their next upload landed there), `POST /auth/logout`,
`PUT /admin/paid-pause` and `PUT /admin/flags` (the admin check used the
middleware's identity), `POST /auth/email` and `POST /abuse-reports`.

**Now.** One middleware (`_csrf_header` in `backend/app/api/main.py`) refuses
every POST/PUT/PATCH/DELETE without the header when sign-in is on (403,
`code: csrf`), multipart uploads and beacons included. The only exemptions
are the two payment webhooks (signed, no cookie). Every write in the
frontend already sent the header (checked: `fetch`, the XHR upload,
analytics and error beacons use `fetch` with the header, no `sendBeacon`).
Cookies are `HttpOnly`, `SameSite=Lax`, `Secure` in production.

Test: `backend/tests/security/test_csrf.py`, parametrised over the route
table (151 write routes), so a new write route without the check fails.

### Path traversal (fixed)

- **Owner ids as folders.** An emailed sign-in makes the owner id
  `email:<address>`, and the address was only checked for an `@` and a dot.
  `a/../../../../tmp/x@evil.com` is deliverable for whoever owns `evil.com`,
  and that owner id becomes a folder in the artifact store
  (`user-<owner>`): voice samples would be written outside the store and the
  account delete would `rmtree` there. Now `members.clean_email` accepts
  only plain address characters (no slash, backslash, quotes, control
  characters, `..`), and the artifact store refuses any key with an empty,
  `.` or `..` part, a backslash, NUL or a leading slash (`_safe_key`), and
  any container that is not 1 to 8 letters and digits.
- **Upload file names.** `Path(name).name` keeps `..` and Windows
  backslashes. An upload named `..` was spooled onto the temp folder itself
  (a 500); one named `..\..\x.mp4` kept that name and it reached share and
  batch zips. Every name from outside now goes through
  `app/filenames.safe_filename` (bare name, both slash styles, no leading
  dots, no control or bidi characters, no Windows-reserved characters, 200
  characters at most): video, voice, word-clip, liveness and reference-file
  uploads, and the link-import `Content-Disposition`.
- **Zip-slip.** Share and batch-export zips now write bare, unique entry
  names (`unique_names`); a second `ok.mp4` becomes `ok-2.mp4` rather than
  overwriting on unzip. The data-export zip uses fixed names (checked).
- **Zip read.** The only zip Voltage reads is a `.docx` reference file. It
  read `word/document.xml` whole: a zip bomb. Now refused above 20 MB
  unpacked, by the declared size and by a capped read.
- Artifact routes already validated `sha256` as 64 hex characters and
  checked the owner first (re-checked).

Tests: `backend/tests/security/test_paths.py`.

### XSS (one fixed)

- **Reference files ran as pages (fixed).** Any UTF-8 text is accepted as a
  project reference file, and it was served with the type its *name* says,
  inline. A file named `x.html` or `x.svg` would run as a page on Voltage's
  own address (an Editor could plant one for the Owner). Now the stored kind
  is the sniffed kind, the response type comes from it (text is
  `text/plain`, PDF stays inline, anything else is an attachment of
  `application/octet-stream`), and every non-PDF answer carries
  `Content-Security-Policy: default-src 'none'; sandbox` (plus the existing
  `nosniff`). Test: `test_a_reference_file_never_runs_as_a_page`.
- No `dangerouslySetInnerHTML` or `innerHTML` anywhere in `frontend/src`;
  React escapes transcripts, comments, briefs and names.
- `frontend/src/lib/markdown.tsx` makes links only from `https?://` targets
  (no `javascript:`), with `rel="noopener noreferrer"`.
- Emails are plain text (Resend `text`), so names in them cannot inject HTML.
- The one server-rendered page (the invoice) escapes every field with
  `html.escape`.
- Notification links are only ever set as `location.hash`.

### Open redirects (none found)

No route takes a `next`/`return` target. The OAuth callback, the email
sign-in callback and the account links redirect only to
`AVE_PUBLIC_URL` plus a fixed hash; the OAuth `state` and PKCE verifier ride
in a signed short-lived cookie and are checked.

### SSE (checked, test added)

`/videos/{id}/events` takes `current_owner` and `_owned`, and the role
middleware applies the Reviewer rules to it like any `/videos/{id}` path.
Owner and Editor: 200; Reviewer: only for a shared video; another person:
404; nobody signed in: 401. Test: `backend/tests/security/test_access.py`.

### Share tokens (checked, test added)

`sh` + 64 random bits of id, then 144 bits of HMAC-SHA256 over id, scope,
target, role and expiry, compared in constant time; revocation and expiry
are read from the row on every open; targets are checked against the
owner's project when the link is made; a file is served only if it is in
that link's own contents. Tests: `tests/store/test_shares.py`,
`tests/api/test_shares_api.py`, and `tests/security/test_share_scope.py`
(one link's token cannot fetch another project's file; swapped signatures
are refused; a turned-off link refuses its page, files and zip).

## 4. Secrets in git history

**How.** `gitleaks git --log-opts=--all --redact` over every branch (52 refs,
8.3 MB scanned). History was not rewritten.

| # | File | Commit | Rule | Verdict |
|---|---|---|---|---|
| 1 | `backend/tests/golive/test_item7_providers.py:372` | `ae03f2a` (on main) | stripe-access-token | Test fixture: a made-up `sk_live_` string inside an error message, used to prove the error reporter scrubs keys. Not a real key. |
| 2 | same file and line | `c806fcc` (branch `hardening/item7-providers`, the same change before cherry-pick) | stripe-access-token | Same fixture. |

No `.env`, database, key or certificate file was ever committed
(`.env`, `.env.*.local` and `backend/var/` are ignored). Suggested: add a
`.gitleaksignore` entry for the two fingerprints, or build the fake key by
concatenation in the test, so the scan runs clean in CI.

## 5. Residual risks

- **No script-src in the CSP** (nginx): the theme uses an inline script before
  first paint. Moving it to a hashed script would allow `script-src 'self'
  'sha256-...'`.
- **Rate limits and the day cap live in one process**; a second server needs
  Redis (known from item 2).
- **The SSRF guard relies on httpcore 1.x internals** (`_pool._network_backend`);
  a test fails if an upgrade changes it. The redirect hops are not limited to
  Google or Dropbox hosts (only to public addresses), so a redirect to any
  public site is followed; the sniffing still refuses anything not a video.
- **Session cookies are not bound to a device**; a stolen cookie works until
  it expires (Google sign-ins) or the password changes (accounts).
- **Proxy headers**: uvicorn trusts `X-Forwarded-*` from anywhere
  (`--forwarded-allow-ips *`). Safe only while the API port is reachable from
  the web container alone (as `docker-compose.yml` has it); Caddy replaces a
  client's own `X-Forwarded-For`.
- **Upload size mismatch** (not security): nginx and Caddy cap bodies at
  520 MB while the app now accepts 2 GB, so uploads above 520 MB fail at the
  proxy with 413.
- Optional Python extras were not audited (see section 1).
