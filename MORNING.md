# Good morning: Voice Consent V1

Branch `overnight/voice-consent`, cut from run 5's `overnight/review-fixes` at `3a3ccac` (run 5 plus addenda 0a, 0b, 3.1, 3.2, 3.3, 3.5). Worktree `../AgenticVideoEditor-vc`.
**Merged into main and pushed on 1 Nov 2026** (fast-forward from `b912fbc`, so run 5 and its addenda are on main too). Everything new here is behind `voices.cloning_verified`, which stays off.

## 0. After the merge

- Live database backed up first: `backend/var/ave.db.bak-20261101-pre-voice-consent` (sqlite `.backup`, at migration 42, integrity ok).
- The next app start applies migrations 0043 to 0055 (run 5's 0043, 0044, 0047 and this run's 0048, 0050, 0053, 0055). The voice records backfill marks p66 and p65's clones video-scoped and the uploaded recording library. Nothing calls the voice vendor during the migration.
- No app servers were running at the merge; start them as usual. Run 5's changes are live from then (section 9 of `git show 0ff88ae:MORNING.md`), including `launch.batch_public` ON.
- Not merged: run 5 addendum a34 ("one state everywhere"), still uncommitted in `../AgenticVideoEditor-a34`, and `feature/one-edit-at-a-time` (its lock work came in through addendum 3.2).
Run 5's summary: `git show 0ff88ae:MORNING.md`. The as-built spec, with every plan item mapped to code and a status table against the plan: `docs/superpowers/plans/2026-10-31-voice-consent-v1.md`.

In one breath:
- **All 8 steps of the plan are built**, one commit each, plus one layout follow-up.
- **The voice guard:** every clone, voicing, save, export and share path goes through `backend/app/safety/voice_guard.py`. A structural test fails if new code reaches the voice vendor anywhere else.
- **Line checks:** 50 of 50 harmful lines caught, 0 of 100 ordinary ad lines falsely blocked (3 runs). Model p95 is 1.49 s on average against the 1.5 s target, one run at 1.61 s. Cost per line is $0.00013.
- **Consent adds 5 clicks**, estimated 12 to 22 s for a person, under the 30 s acceptance.
- **Real spend: $0.16** (line-check evals only).
- **Not done before the public:** lawyer review, grievance officer details, a retention purge, a cloning step in the rehearsal journeys.

## 1. What shipped

| Step | What | Commit |
|---|---|---|
| 1 | Migration 0048: `voice_records` (scope and status per vendor voice id, beside the JSON voice lists) and the five plan tables; dry-run tool | 2194e26 |
| 2 | `voice_guard` service and its routes (`app/voice_guard_api.py`) | 7082fd5 |
| 3 | Every enforcement point wired; route and vendor-call enumeration tests | 55e1f1a |
| 5 | Public-figure block on clone (WavLM, 0.92 block, 0.84 review), no-go list and borderline queue in admin; migration 0055 | 3f1f0d4 |
| 4 | Line checks: rules in English, Hindi and Hinglish, Haiku 5.5 check, review queue, strikes; migration 0050 | c0e933d |
| 7 | AI voice tag on the first 3 s, description file, permanent metadata, Trace, Suspend and Restore; migration 0053 | dc7084c |
| 6 | Attestation modal, export reminder, line refusal copy, "This video only", "Prove it's your voice", agent pause on the card | 2b4c42a |
| 8 | Terms and Acceptable Use v3 drafts, Grievance Officer placeholders, Help "Using voices responsibly", RUNBOOK section 7, statement hash test | b5e186c |
| 6+ | The attestation card's buttons stay in view at 1280x720 | c090715 |
| - | Gate: the billing test pins its clock | d526bd3 |

Migrations 0049, 0051, 0052 and 0054 are reserved gaps.

## 2. Migration counts (dry run on a copy of your live database)

| Existing voice | Count |
|---|---|
| Designed or stock voice | 0 |
| Clone with a passed own-voice check | 0 |
| Any other clone, now video scope | 2 (p66, and p65 in the Bin) |
| Clone whose source video is deleted | 0 |
| Uploaded recording (not in the plan), now library | 1 |

All four passed checks in the live DB are the old stand-in check, so none counts as proof. Down restores the copy exactly.

## 3. Line-check eval (3 runs, mean and range)

| Mode | Blocks caught | False blocks (of 100) | Ordinary held | p50 | p95 | Cost a line |
|---|---|---|---|---|---|---|
| One line a call | 50/50 (35 by rules) | 0 | 1.7 (1 to 2) | 0.87 s | 1.49 s (1.39 to 1.61) | $0.00013 |
| Ten lines a call | 50/50 | 0 | 0.7 (0 to 1) | 2.12 s | 3.66 s | $0.000035 |

Thinking off (`AVE_LINE_CHECK_THINKING=off`) gets p95 to about 1.1 to 1.3 s but falsely blocked 2 of 100; it stays on. Set: `backend/evals/line_checks/lines.json`.

## 4. Decisions to confirm (details in DECISIONS.md, "Voice consent V1")

1. Uploaded recordings of your own voice become library with no check linked.
2. A clone whose video is in the Bin stays video-scoped, so Restore works.
3. Google and sign-in-off accounts count as a verified email.
4. A voice proven to be your own needs no attestation.
5. With the flag on, a passed own-voice check opens Save to My voices without `voices.cloning`.
6. Lip-sync and voice design are not guarded (neither clones or voices).
7. A held clone (no-go 0.84 to 0.92) does not resume by itself after approval; the user voices again.
8. With no-go entries but no speaker model, every clone is held.
9. The user never sees which no-go entry matched or the score.
10. Block sentences for impersonation, political, sexual, minors and hate were written by the builder (fraud is the plan's).
11. Model call fails: cloned voice lines are held, stock voice lines pass on rules with a warning.
12. Translations of a fully passed master are checked by rules only.
13. A suspension also stops a voice cloned from your own uploaded recording.
14. The export description file is served but not linked on the Export page yet. Where should it go?
15. The tag: volt with ink text, top left, 5% of the short side (lower on 9:16).
16. Metadata keeps "contains AI-generated voice" even when the label is switched off.
17. Extra labels: "Held for a check", "Cleared", "Not cleared"; several voices read "Asha's and Ravi's voices".
18. New legal sections show a visible "New, pending legal review" stamp.
19. Political, election and sexual content are banned outright in synthetic voices (v2 allowed labelled political ads).
20. Suspend cloning (all of a user's cloned voices) is the only disable; there is no per-voice switch.

## 5. Status against the plan

All 13 test checkboxes: done (see the spec's table for the test of each).
Acceptance:
- All tests green: see section 6. Rehearsal journeys with a cloning step: **not done** (`e2e/rehearsal/*` has none).
- 50-line set: **done**, targets met except the p95 edge.
- 30 s for a beta user: **estimate only** (5 clicks, 12 to 22 s), not timed with a person.
- Lawyer review: **not done**.

## 6. Gates

Each step passed `make launch-check SKIP_ENV=1` on its own branch (step 8's Playwright needed reruns: axe scans timed out at 60 s under load 25 to 110, each passed on rerun). Combined on this branch: steps 1 to 5 green (backend 2692, vitest 647, Playwright 166); steps 1 to 7 green (backend 2724, vitest 678, Playwright 175); **the final tree (all 8 steps, the follow-up and the billing test fix): all steps passed** (backend 2733 passed, 17 skipped; vitest 680/680; build; lint; Playwright 175/175; migrations ok; em dash check).

One existing test broke on the calendar, not on this run: `tests/golive/test_billing.py::test_trial_plan_credits_topups_and_invoices` read the real clock, so from 1 Nov October's plan credits lapsed (it failed on `overnight/review-fixes` too). Its clock is now pinned to 31 Oct 2026 (d526bd3); the billing code is unchanged.

## 7. Launch blockers before `voices.cloning_verified` goes public

1. Lawyer review of the copy, Terms, Acceptable Use and retention.
2. Grievance Officer name and contact (placeholders in the legal pages).
3. A retention purge (nothing deletes attestations, line checks or the synthesis log yet).
4. A cloning step in the rehearsal journeys.
5. Region: cloning is only gated by who has the flag; the India-first country gate is described in the spec as V2.

## 8. Setup as it ran

Builders on `vc/step<N>` (worktrees `../AgenticVideoEditor-vc4` to `-vc8`, `-vc6b`), each cherry-picked here. Steps 1 to 3 were built on this branch directly. Run 5 addendum a34 ("one state everywhere") is still uncommitted work in `../AgenticVideoEditor-a34` from 2026-10-28; not touched.
