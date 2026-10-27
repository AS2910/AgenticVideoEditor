# Launch rehearsal journeys

Four browser journeys that run against the real rehearsal stack. That stack is the shipped
docker-compose set (app, worker, web nginx, Postgres), with `AVE_LAUNCH_PROFILE=public`,
`AVE_AUTH=accounts` and every vendor mocked. Nothing is mocked in the browser. Each run makes
new accounts with unique addresses (`<who>+<time>@rehearsal.test`) and deletes them at the end.

## Run

```sh
scripts/rehearsal.sh up                     # build and start the stack on http://localhost:8080
cd frontend
npx playwright test -c playwright.rehearsal.config.ts            # all four, one after another
REHEARSAL_VIDEO=1 npx playwright test -c playwright.rehearsal.config.ts   # also writes docs/rehearsal/*.mp4
```

- The shipped sign-in limit is 20 auth requests per 10 minutes per address, and one full run
  uses about 13 from this machine. Before running again within 10 minutes, clear the
  in-memory limits with a restart:
  `scripts/rehearsal.sh dc restart app && until curl -fsS localhost:8080/api/ready; do sleep 2; done`.
- `REHEARSAL_URL` points the journeys at another stack (the default is http://localhost:8080).
- Emails are not sent. The journeys read them from the stack's dev outbox (the Postgres
  `notify_outbox` table) through `scripts/rehearsal.sh sql`.
- The videos are screenshots taken about every 500 ms, stitched by the system ffmpeg
  (`/opt/homebrew/bin/ffmpeg`, or set `FFMPEG`). They are H.264 at 720p and play at about real time.
- Allow 2 to 5 minutes for a full run on a loaded machine. Turns take 10 to 20 s and renders 5 to 20 s.

## The journeys

| Spec | Who | What it covers |
|---|---|---|
| `owner.spec.ts` (`owner.mp4`) | A new owner | Sign up with the Terms accepted (the button stays off until they are). Open the confirm link from the outbox and land signed in on Home. Open the sample project and its video. Upload the sample clip and the editor opens on it. Take a turn ("Add a short line at the start"), answer the voice consent (a test-mode read-aloud upload) and the "Go ahead" gate, then the proposal row "Fresh every morning." lands Proposed. Add it, and the row says it is in the video. Export: Rendering, then Rendered, then the Download MP4 link. Billing: a top-up in test mode ("no money moved"). Members: invite a Reviewer and share the sample project. Settings: delete the account, which signs you out, and signing in again fails. |
| `reviewer.spec.ts` (`reviewer.mp4`) | A Reviewer | An owner made through the API shares their sample project and keeps one standalone video private. The reviewer opens the invite email's link, signs up and confirms, comes back to the invite and accepts it. Home shows only the shared project and its two videos, never the private one, and nothing to upload. The shared video loads and plays. The editor has no composer and no Export, and says why in one sentence ("You are a Reviewer in this workspace..."). Billing is not in the side nav, and #billing says it belongs to the owner. The reviewer deletes their account, and the owner and all three of their videos are still there. |
| `editor.spec.ts` (`editor.mp4`) | An Editor | Invited by an API-made owner the same way. Opens the owner's video and it plays. Takes a turn and adds the proposal, and the owner's API sees the line in their video. Billing is not offered (#billing says it is the owner's). Members shows their Editor role with no invite form. Deletes their account, and the owner and their videos are still there. |
| `batch.spec.ts` (`batch.mp4`) | A new owner, batch (run 5 item 9) | Signs up on the public profile and sees `launch.batch_public` and `projects.batch` on (and `projects.review` off). Two more cuts of the ad go into the sample project. B1: the first-use steps, the example "Make every offer line say 25% off" fills the box, Plan it for 3 videos, the gate ("You pay at most", **Go · 3 videos** last), the board's one-sentence summary, Batch finished, a ready row's "Hear the changes in" link, Add all that passed. B2: a Hindi version of one video, stacked under it, its batch finished. B3: every video picked (no stages, no "Not approved"), Export, every file Ready, Download all (.zip), Share link. Deletes the account. |

Every journey also checks the following:
- While a turn runs, the Voltage pane's status line always says something. It shows Working, then Needs your go, while the row chip shows Voicing or Rendering, and the status strip shows "Rendering preview v1, about N s".
- The export page shows Rendering… and then Rendered.
- There is no visible `role=alert` error banner at each step.
- No 5xx response or page error happens behind the journey.

Helpers (sign up, the outbox, the API owner, consent, turn, add, delete, and the recorder) are in
`frontend/e2e/rehearsal/helpers.ts`.
