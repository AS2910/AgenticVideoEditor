# Phase 9c · Sign-in

**Date:** 2026-10-04 · **Status:** built, from the Phase 9 design ("OIDC sign-in, Google first → a session cookie → `current_owner()`; localhost stays open; a login page, CSRF on writes, per-user quotas").

## What changed

**Sign-in is a switch.** `AVE_AUTH=off` (the default) keeps everything as it was: one local owner, no door. `AVE_AUTH=google` turns the door on; it needs `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AVE_SESSION_SECRET` (any long random string) and `AVE_PUBLIC_URL` (the origin the browser uses; the redirect URI to register with Google is `{AVE_PUBLIC_URL}/api/auth/callback`). `AVE_ALLOWED_EMAILS` makes a private Voltage: a comma-separated list of emails or `@domains`; anyone else is told it is private.

**How it works.** `GET /auth/login` sends the browser to Google (authorization code + PKCE; the state and verifier travel in a 10-minute signed cookie). `GET /auth/callback` checks the state, exchanges the code, asks Google's UserInfo endpoint who signed in (so no JWT is verified here and no crypto library is needed; `httpx` was already a dependency), checks the allow-list, and sets a 30-day HttpOnly, SameSite=Lax session cookie signed with HMAC-SHA256. `current_owner()` reads it: the owner is `google:{sub}`, and every project route was already scoped by owner since Phase 9. `GET /auth/me` says whether sign-in is on and who is here; `POST /auth/logout` clears the cookie. Nothing new is stored server-side: a session is its cookie.

**CSRF.** With sign-in on, a state-changing request must carry `X-Requested-With: voltage`, which a cross-site form cannot set; the API client adds it to every POST, PUT and DELETE, including the upload (it does not touch the multipart boundary). Without it: 403.

**Per-user quota.** `AVE_USER_BUDGET_USD` (default $10) caps estimated spend across one person's projects, on top of the per-project cap; the usage route reports both and the refusal says "across your projects".

**The front end** asks `/auth/me` before showing anything: with sign-in on and nobody in, the door (one button: Sign in with Google); otherwise the start screen with the person's name and Sign out in the header. A 401 anywhere sends them back to the door with "Your session ended".

## Where

`app/auth.py` (tokens, PKCE, `GoogleProvider`, the allow-list), `app/config.py` (`auth_mode` and friends; `AVE_AUTH=google` without its keys refuses to start), `app/api/main.py` (`current_owner(request)`, `_ensure_spend`, the four `/auth/*` routes), `app/usage.py` (`spent_usd_by_owner`, `UserCeilingReached`); `frontend/src/components/SignIn.tsx`, `api.getMe` / `logout` / `loginUrl`, the `FROM_VOLTAGE` header, `App` (`me`, `signOut`).

## Exit

497 backend + 193 frontend tests; lint, typecheck and build clean. Live, with a throwaway backend on :8010 and placeholder Google credentials: `/auth/me` says sign-in is on, `/projects` answers 401, `/auth/login` redirects to Google with the right redirect URI and PKCE challenge and sets the login cookie, and a callback with a bad state is refused. The real Google round-trip is covered by tests with a mock transport; it has not been exercised against Google, which needs an OAuth client in Google Cloud Console (web application; authorised redirect URI as above).

## Left for later

A session store, if sign-out everywhere or revocation is needed (today a session lives in its cookie until it expires). Other providers behind the same `Provider` protocol. Serving the built front end from the backend for a single-origin deployment (the Vite proxy covers development).
