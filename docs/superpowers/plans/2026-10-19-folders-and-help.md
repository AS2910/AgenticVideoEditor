# Projects as folders · Tutorial map and Help (2026-10-19)

Two of the user's documents, built on top of Volt: **"Projects as Folders"** (a project becomes a folder of videos; today's project becomes a Video) and **"Tutorial Map and Help"** (a guided run on the sample ad, first-time tips, a get-started checklist, Ask Voltage for help, a keyboard sheet, a Help page). The design canvas row 4 ("Learning") and row 5 ("Projects as folders") are the screens: `Home`, `ProjectPage`, `MoveDialog`, `EditorHeader`, `TourRun`, `Guides`, `Shortcuts`, `Help`.

This file is the **contract** between the backend, the pages and the editor. Names below are final.

## Names

| Word | Means |
|---|---|
| **Video** | today's project record: one clip, its transcript, speakers, turns, proposals, takes, edits, exports, settings. Ids stay as they are (`p12`). |
| **Project** | a folder: name, brief, default settings, shared voices, reference files, an optional spending ceiling. Ids are `f<n>`. |
| `video_id` | a video's id, in every API payload that names one (a video record or summary, a plan, a candidate, a message, a receipt, a usage row). |
| `project_id` | the folder a video is in, or `null`. Never a video's own id. |

Python may keep its internal attribute names (`ProjectRecord.project_id` is the video id inside the backend); **serialisation follows the table above**.

## Storage

- `projects` table → renamed `videos` at startup when `videos` does not exist yet (`ALTER TABLE projects RENAME TO videos`); gains `project_id TEXT NULL` (the folder). Child tables keep their `project_id` column (it is the video id); the ledger (`usage`) gains `folder_id TEXT NULL`, copied in at the time of the charge.
- New `projects` table: `id TEXT PK` (`f<n>`), `owner`, `name`, `brief TEXT NOT NULL DEFAULT ''`, `settings TEXT JSON` (defaults for new videos: autonomy, turn_usd, effort, ask_before), `ceiling_usd REAL NULL`, `created_at`.
- Project voices: meta `project_voices:{project_id}` holding a JSON list of entries shaped like `my_voices` entries (`voice_id, name, kind, description, sample_sha, at, consent`).
- Project files: `project_files:{project_id}` meta list `[{name, sha256, size, kind, at}]`; bytes under the artifact store at `projects/<project_id>/files/<sha256>`; text is extracted where it can be (txt, md, json, csv; pdf and docx best effort) and kept as `text` on the entry (capped at 20 000 chars) so `read_project_files` can search it.
- Brief suggestions: `brief_suggestions:{project_id}` meta list `[{id, text, why, video_id, at}]`.
- Settings resolve most specific first: **video → project → user**. A video uploaded into a project copies the project's defaults into its own settings at creation. A missing key on the video reads the project's, then the owner's prefs.
- Spending: the project's ceiling (when set) joins the same reservation as the video's and the user's; the lowest wins. `GET /videos/{id}/usage` adds `project_ceiling_usd` and `project_spent_usd` when the video is in a project.
- Variants land in the same project as the original. Deleting a video inside a project touches nothing else.
- Migration: every existing project row becomes a standalone video; nothing else moves.

## API

Video routes: every `/projects/{id}/…` route of today moves to **`/videos/{id}/…`** unchanged inside; the old `/projects/{id}/<sub>` paths answer as aliases for one release (`deprecated=True`), **except** `GET /projects/{id}`, `DELETE /projects/{id}` and `POST /projects`, which now belong to folders. The upload is `POST /videos` (multipart; optional `project_id` form field). `GET /videos?project=none|<id>&recent=N` lists videos (`recent` across everything, newest first; `project=none` the standalone ones). `GET /videos/{id}` and `DELETE /videos/{id}` as before. **`PATCH /videos/{id}` `{"project_id": "<id>"|null, "voice": "copy"|"keep"|null}`** moves a video; when it leaves a project whose voices its kept edits or ready proposals use and `voice` is not given, it answers **409** `{"detail": "…", "voices": [{"voice_id","name"}]}`; `copy` adds those voices to the video's own made voices, `keep` adds them to the owner's `my_voices`. A video summary and record carry `video_id`, `project_id`, `project_name` (or null).

Folder routes:

| Route | Body / answer |
|---|---|
| `GET /projects` | `{"projects": [{project_id, name, brief, video_count, voices, files, ceiling_usd, spent_usd, created_at, last_at}]}` |
| `POST /projects` `{name, brief?}` | 201, the project |
| `GET /projects/{id}` | `{project: {project_id, name, brief, settings, ceiling_usd, spent_usd, created_at}, videos: [video summaries], voices: [entries + used_in], files: [{name, sha256, size, kind, at}], suggestions: [{id, text, why, video_id, filename, at}]}` |
| `PATCH /projects/{id}` `{name?, brief?, settings?, ceiling_usd?}` | the project |
| `DELETE /projects/{id}?videos=delete\|keep` | 204; `keep` makes its videos standalone; project voices go unless kept in someone's voices |
| `GET /projects/{id}/videos` | `{"videos": [...]}` |
| `POST /projects/{id}/files` (multipart `file`) · `DELETE /projects/{id}/files/{sha256}` · `GET /projects/{id}/files/{sha256}` | the entry / 204 / the bytes |
| `POST /projects/{id}/voices` `{voice_id}` · `DELETE /projects/{id}/voices/{voice_id}` | share one of the owner's voices (mine or made) into the project / unshare |
| `POST /projects/{id}/suggestions/{sid}/accept` · `…/dismiss` | accept appends the text to the brief; both remove the suggestion; answer the project |

`GET /voices` gains `project: [{...entry, project_id, project_name}]` (voices shared in the owner's projects). `GET /usage?period=` renames its per-video list to **`by_video`** and adds **`by_project`** (`[{project_id, name, videos, turns, spent_usd, ceiling_usd}]`).

Tutorial and help (coordinator's modules, mounted as routers): `GET /help` `{"articles": [{slug, section, title, summary, body, tour}]}`, `GET /help/search?q=`; `GET/PUT /me/onboarding` `{tour: {step, finished, skipped}, tips: [ids], checklist: [ids], checklist_hidden}`; `POST /tutorial` → the sample video record (flagged `settings.tutorial = true`; no vendor is called). On a tutorial video, `POST /videos/{id}/turns` is answered by `app.tutorial.replay_turn(...)` instead of the agent: `main.py` branches on `settings.tutorial`.

## The agent

- The opening view, when the video is in a project, starts with a **Brief** block (the project's name and brief, the shared voices by name, the sister videos by name and length) above the video's own facts; cached with it.
- `list_voices` lists the project's voices first, marked "in this project"; choosing one needs no new consent when the project's entry carries one.
- New FREE tools: `list_project_videos()` (each sister video: name, length, state, the voices and wording it shipped), `read_project_files(query)` (searches the reference files' text; returns matching passages with the file name), `suggest_brief(addition, why)` (records a suggestion for the project page; the brief changes only when the user accepts), `search_help(query)` (the help articles; returns up to three with slug, title, section, summary, body excerpt, tour).
- Prompt rules: a turn changes only its own video — read sisters, never edit, ship or delete them; a "how do I…" question is answered from the help articles, naming the one used, never guessing at a feature, and when the question is really a request, offer to do it under the usual gate.
- A step message from `search_help` carries `data.help = [{slug, title, section, tour}]` so the pane can show "From Help · Section / Title" with Show me / Read more.

## Routes in the browser

`#home` (also `#projects` and `#`), `#v/<video_id>`, `#v/<video_id>/export`, `#p/<project_id>`, `#voices`, `#usage`, `#settings`, `#billing`, `#help`. Old `#p12` links redirect to `#v/p12`. The nav is Home · Voices · Usage · Settings · Help.

## Screens

- **Home** (`Home.dc.html`): a sidebar of projects (+ New project inline; "Standalone videos" with a count), the hero ("What should your next video say?"), the drop zone with an **Add to** picker (No project / each project) and a note under it, **Recent videos** with tabs All · In projects · No project, cards with a project chip (dashed "No project"), each card's ••• with Move to project… and Delete.
- **Project page** (`ProjectPage.dc.html`): breadcrumb ← Home / Projects, the name (56 px display), the tag line (N videos · N shared voices · N files · $spent of the $ceiling project ceiling), ••• (rename, delete), **+ Upload to this project**; left: the videos as cards with a state stamp and a drop zone card, the "Later: batch turn" black strip; right: Brief (textarea, Voltage's suggestion card with Add to brief / Not now), Shared voices (+ Add), Reference files (+ Add), Defaults for new videos (autonomy, money per turn, project ceiling with a bar).
- **Move to project** (`MoveDialog.dc.html`): a dialog (560 px, ink border, 8 px volt offset shadow) with the file name, "Now in X. Its turns, takes and edits stay with the video wherever it goes.", a radiogroup of destinations (current marked, No project dashed, + New project…), the voice question when leaving a project whose voice the video uses (Copy the voice into this video / Keep it in my voices), Cancel and Move to X / Remove from project / Keep it here; afterwards a toast with Undo.
- **Editor header** (`EditorHeader.dc.html`): VOLTAGE / [folder crumb ▾] / filename · length; the crumb's menu: Open <project> (N videos), Move to project…, the brief Voltage is using with Edit brief →; a standalone video shows a dashed "No project · Add to project" crumb; the spend reads `$video · $spent/$ceiling project`. The pane's header gets chips: Brief · <project>, N shared voices, N files.
- **Tour** (`TourRun.dc.html`): welcome card → seven steps (spotlight with a 2 px volt ring and a dimmed backdrop; the coach card with Step n of 7, Skip tour, title, body, a hint, progress dots, Back, the action) → done card with Upload a video / Replay; a toast "Tour skipped. Replay it any time from Help." The highlighted control stays usable; every step waits for the user's own click.
- **Guides** (`Guides.dc.html`): a tip (black card with a volt offset shadow and a caret, a section tag, the sentence, a help link, Got it) pointing at a control; the Get started pill (bottom left, ink with volt text, "Get started 2/5") opening a checklist card (progress bar, five rows with a box, Show me → on the ones left, Hide); the pane answering a "how do I" with a one-line trace (`search_help`), the answer, a "From Help · Section" card with ⚡ Show me and Read more, then the offer to do it.
- **Keyboard sheet** (`Shortcuts.dc.html`): `?` opens, Esc closes; two columns (Move and listen / Change) of `.kbd` keys; the footer line about money; All of Help →.
- **Help** (`Help.dc.html`): "How can we help?" with the search box (ink offset shadow), Replay the tutorial (volt, "3 min · sample ad · free"), Ask Voltage (ink), the ten sections in a grid with numbered tags and article buttons, the article reader as a right-hand drawer (Close, title, body, ⚡ Show me, Ask Voltage about this, Was this helpful?), the "Still stuck?" black strip with Keyboard shortcuts.

## Decisions the documents left open (taken as recommended)

One project or none per video; no nesting; access follows the workspace; a batch turn across videos is later (the strip on the project page says so); the project ceiling is off unless set; deleting a project always asks (delete its videos or move them out). The tutorial's recorded turn and take come from one real run on the sample ad, saved under `backend/app/tutorial/fixture/`; replaying it never calls a vendor and the ledger stays at $0.00. Help articles live in `help/articles/<section>/<slug>.md` at the repo root with front matter (`title`, `section`, `order`, `tour`), read by the backend for both the Help page and `search_help`.

## As built (2026-10-19)

**Backend** (697 passed, 2 skipped). The `projects` table is renamed `videos` at startup and every existing row becomes a standalone video; the id counter carries on. Folders live in a new `projects` table (`f<n>`). All 28 video sub-routes moved to `/videos/{id}/…` with deprecated aliases under `/projects/{id}/…`. `PATCH /videos/{id}` moves a video; its 409 names the project voices in use (not ones the destination shares, nor ones the video already carries). Project spend counts only charges made while the video was in the project (`usage.folder_id`); the lowest of the video, project and user ceilings wins. Settings resolve video → project → user per key. Deleting a project needs `?videos=delete|keep`. Reference files: txt, md, json, csv and docx are read for `read_project_files`; **PDF text stays empty until `pypdf` is installed**. The agent's opening view starts with a Brief block inside a project; four FREE tools (`list_project_videos`, `read_project_files`, `suggest_brief`, `search_help`); a `search_help` step carries `data.help`. Help articles: 39 Markdown files under `help/articles/`, served by `GET /help` and `/help/search`. Onboarding: `GET/PUT /me/onboarding`. Tutorial: `POST /tutorial` makes the sample ad a tutorial video; its turns replay `app/tutorial/fixture/` (recorded from one real run on 2026-10-19, $0.14, video p57) and spend nothing; the tour covers one edit, then says so.

**Front end** (274 tests). Routes `#home`, `#p/<id>`, `#v/<id>`, `#v/<id>/export`, `#help[/<slug>]`; old `#p12` links still open the video. Home (sidebar of projects, + New project, Add to picker, tabs, project chips, ••• Move to project… / Delete…), the Project page (brief with autosave and Voltage's suggestions, shared voices, reference files, defaults and ceiling, delete with the choice about videos), the Move dialog (with the voice question), the editor's project crumb and menu, the pane's context chips, Usage's By project table, Voices' "In a project" section, Export's note on where a variant lands. The tour engine (`src/tour/`), the guided run and five Show me tours, ten first-time tips, the Get started checklist (ticked by real actions: a goal sent, a proposal added, the export page opened, a voice kept, autonomy or the cap changed), the keyboard sheet on `?`, the Help page, the "From Help" card under a how-to answer.

**Left out or approximated.** The first-project-voice tip has no trigger yet (it needs the take's voice to be known as a project voice on the client). "Export a video" ticks when the export page opens, not when the render finishes. Help's "Was this helpful?" is not recorded anywhere. The tour's analytics events (started, step reached, skipped at N) are not sent; the onboarding record keeps the step reached, finished or skipped. Sharing a project with teammates, nesting and the batch turn are later, as the documents say.
