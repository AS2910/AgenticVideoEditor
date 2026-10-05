# Agentic Video Editor — User Stories

**Date:** 2026-10-04 · **Status:** derived from the repository as it stands (README, specs, plans, commit history, and the one-line stories agreed on 2026-10-03). Each story is in Mike Cohn form with one Gherkin scenario, so QA can test it and the backlog can be groomed from it. IDs keep the agreed A–I groups; new stories found in the code but not in the agreed list are marked **(new)**.

**Status key:** **Built** — in `main` and covered by tests · **Built (partial)** — works, with a documented seam · **Backlog** — designed, not built; the blocking phase is named.

## Personas

- **Marketing video editor** — on a marketing / ad / social team; owns a short brand video that has a wrong number, a flubbed line or a changed offer, and cannot afford a reshoot. The primary v1 user.
- **Social video creator** — a talking-head or travel creator with their own footage, sometimes with no speech at all (the Goa beach clip). Secondary, but the silent-clip work was built for them.
- **Signed-in team member** — someone using a shared, public Voltage who must see only their own projects and have their own spend ceiling.
- **Account holder** — the person whose vendor keys and money are being spent; may be the same human as the editor, but cares about a different thing.

---

## A · Understanding the clip

### User Story A1
- **Summary:** Show every line, who said it and when, so the editor knows what there is to change
- **Status:** Built (Phases 3, 10, 11; UX-2)
#### Use Case
- **As a** marketing video editor
- **I want to** see the clip's speech as a transcript with each line's time and speaker
- **so that** I can find the moment I need to fix without scrubbing the video
#### Acceptance Criteria
- **Scenario:** A clip with two speakers is uploaded
- **Given:** I have uploaded a video under three minutes with an audio track
- **and Given:** transcription and speaker detection have finished
- **When:** the goal stage opens
- **Then:** I see one row per line with its start time, its words as spoken, and a speaker named by role (e.g. *the Customer*) that I can confirm with "Looks right" or rename

### User Story A2
- **Summary:** Tell the editor what Voltage can and cannot do before they type
- **Status:** Built (UX-2, Phase 8)
#### Use Case
- **As a** marketing video editor using Voltage for the first time
- **I want to** be told in one specific sentence what the clip contains and what kinds of change are possible
- **so that** I ask for something the tool can actually do instead of discovering its limits by trial
#### Acceptance Criteria
- **Scenario:** First look at a transcribed clip
- **Given:** the goal stage is open on a clip with speech
- **and Given:** Voltage has read every line
- **When:** I read the opening line under the orb
- **Then:** it names what is and isn't said in this clip, offers example goals, and a request that is not about speech (e.g. "make it brighter") gets a reply in the chat rather than a failed job

### User Story A3
- **Summary:** Write and place a voice-over on a clip that has no speech
- **Status:** Built (UX-5)
#### Use Case
- **As a** social video creator with a silent clip
- **I want to** ask Voltage to look at the picture and add a line introducing the place
- **so that** my footage gets a narration without me writing or timing it myself
#### Acceptance Criteria
- **Scenario:** A brief with no words on a 7.5 s beach clip
- **Given:** I have uploaded a clip whose audio has no speech
- **and Given:** the goal stage shows the frame strip and Voltage's sentence about the picture
- **When:** I send "Add an audio introducing the place to the audience"
- **Then:** the plan holds a voiced line placed at a time, with two alternative wordings as suggestions and one sentence on why that one was chosen, instead of the "no speech to change" strip

### User Story A4 (new)
- **Summary:** Be asked at most three picture-driven questions when the brief is vague, each with a guess
- **Status:** Built (UX-5 SV-3)
#### Use Case
- **As a** social video creator who is not sure what the clip should say
- **I want to** ask "look at this and help me" and answer short questions one at a time
- **so that** I get a line that fits my intent without having to describe it fully up front
#### Acceptance Criteria
- **Scenario:** Help-me brief on a silent clip
- **Given:** the clip has no speech and Voltage has looked at its frames
- **When:** I send "look at the video and help me"
- **Then:** Voltage says what it sees and asks one question with its own guess, continues to at most three, offers "Go with your guesses" throughout, and plans after the last answer

### User Story A5 (new)
- **Summary:** Try the whole journey on a bundled sample before uploading my own footage
- **Status:** Built
#### Use Case
- **As a** marketing video editor evaluating the tool
- **I want to** start from the bundled sample ad
- **so that** I can see the edit loop end to end without hunting for a suitable clip
#### Acceptance Criteria
- **Scenario:** Use the sample ad
- **Given:** I am on the start screen
- **When:** I click "use the sample ad"
- **Then:** the sample is uploaded and transcribed through the same path as any file and lands on the goal stage with its words at their timings

---

## B · Asking for changes

### User Story B1
- **Summary:** Give one goal for the whole video and get a reasoned plan to approve
- **Status:** Built (Phase 13)
#### Use Case
- **As a** marketing video editor
- **I want to** state a goal for the whole video ("the offer is now 30%, and drop the second CTA")
- **so that** Voltage finds every line the goal touches instead of me editing them one by one
#### Acceptance Criteria
- **Scenario:** Goal across several lines
- **Given:** the goal stage is open and speakers are confirmed
- **and Given:** autonomy is "Check with me" (the default)
- **When:** I send the goal
- **Then:** I see what Voltage noticed as it read, a plan of ticked changes each with new words and a plain-word reason, any extra suggestions unticked, and a cost and time estimate, with nothing voiced yet

### User Story B2
- **Summary:** Change one line in place without going to the panel
- **Status:** Built (UX-1)
#### Use Case
- **As a** marketing video editor
- **I want to** click a line in the transcript and give it new words
- **so that** I can fix a single flub quickly, at the line, without composing a request
#### Acceptance Criteria
- **Scenario:** Reword one line from the row
- **Given:** the editor is open with a transcript
- **When:** I click a line, type new wording and preview it
- **Then:** the row shows Working then Ready with the take playable in the row, and nothing elsewhere in the transcript has changed

### User Story B3
- **Summary:** Change one word or number and have the edit cover only that word
- **Status:** Built (Phases 3, 8)
#### Use Case
- **As a** marketing video editor
- **I want to** say `change "20% off" to "30% off"`
- **so that** only the changed words are re-voiced and the rest of the line stays as shot
#### Acceptance Criteria
- **Scenario:** Quoted-text change
- **Given:** the transcript contains the words "20% off"
- **When:** I send `change "20% off" to "30% off"` in Voltage's box
- **Then:** the selection snaps to those words' real timings and the take replaces only that span

### User Story B4
- **Summary:** Add a new line after an existing one
- **Status:** Built (UX-1)
#### Use Case
- **As a** marketing video editor
- **I want to** add a line after a given one ("add 'Thirsty?' after line 2")
- **so that** I can insert a message that was never shot
#### Acceptance Criteria
- **Scenario:** Add a line after
- **Given:** a line is focused in the transcript
- **When:** I choose "Add a line after" (or press A) and give the words
- **Then:** a new row appears after it at its own time with the take playing over the picture by default

### User Story B5
- **Summary:** Remove a line and leave the room's own silence in its place
- **Status:** Built (UX-1; mute, not cut)
#### Use Case
- **As a** marketing video editor
- **I want to** remove a line or a word
- **so that** a wrong claim disappears without a visible or audible hole
#### Acceptance Criteria
- **Scenario:** Remove a line
- **Given:** a line is focused
- **When:** I choose Remove (or press Delete)
- **Then:** its words are gone, the span is filled with room tone taken from the recording's own gaps, the picture is untouched, and the row offers Undo

### User Story B6
- **Summary:** Change how a line is said without changing its words
- **Status:** Built (UX-1, UX-2)
#### Use Case
- **As a** marketing video editor
- **I want to** mark a line warmer, more excited, calmer, slower or firmer
- **so that** the delivery matches the moment, not just the words
#### Acceptance Criteria
- **Scenario:** Warmer delivery
- **Given:** a line's editor or plan item is open
- **When:** I pick "warmer" under Delivery and preview
- **Then:** a new take is voiced with that delivery and the words unchanged, and the chip shows as pressed

### User Story B7
- **Summary:** Be asked only when it matters, and always with a guess I can accept
- **Status:** Built (Phases 8, 13, 14)
#### Use Case
- **As a** marketing video editor
- **I want to** be asked at most one thing Voltage genuinely cannot decide, with its own guess
- **so that** I can say "go" and keep moving instead of answering a questionnaire
#### Acceptance Criteria
- **Scenario:** Ambiguous goal
- **Given:** I have sent a goal that could apply to two lines
- **When:** Voltage plans
- **Then:** it asks one question with its guess filled in, an empty answer accepts the guess, and the plan is rebuilt with the answer

### User Story B8
- **Summary:** Adjust the plan in my own words without losing the takes already voiced
- **Status:** Built (UX-2)
#### Use Case
- **As a** marketing video editor
- **I want to** type "not the second one" or "warmer at 0:17" against the current plan
- **so that** I can steer it without re-stating the whole goal or paying for lines again
#### Acceptance Criteria
- **Scenario:** Revise the plan in words
- **Given:** a plan exists and some items are already Ready
- **When:** I send "not the second one" in Voltage's box
- **Then:** the second item is unticked in place and every Ready take survives unchanged

### User Story B9 (new)
- **Summary:** Ask Voltage for a wording I can edit before anything is voiced
- **Status:** Built (Phase 12)
#### Use Case
- **As a** marketing video editor who knows what the line must convey but not how to say it
- **I want to** ask Voltage for a rewrite of a line and edit it before previewing
- **so that** I get a line that fits the slot without paying for a take I will discard
#### Acceptance Criteria
- **Scenario:** Ask for wording
- **Given:** a line's editor is open
- **When:** I click "Ask Voltage for wording"
- **Then:** a suggested wording written to the line's syllable budget appears in the editor, editable, and no voice call has been made

### User Story B10 (new)
- **Summary:** Let the plan run as soon as it is made when I trust it
- **Status:** Built (Phase 13)
#### Use Case
- **As a** marketing video editor on a routine change
- **I want to** set the project to "Just do it"
- **so that** I hear the result straight away instead of approving each plan
#### Acceptance Criteria
- **Scenario:** Autonomous run
- **Given:** the project's autonomy setting is "Just do it"
- **When:** I send a goal
- **Then:** the plan is returned with a job already voicing it, and the panel narrates each take as it goes

---

## C · Judging the result

### User Story C1
- **Summary:** Hear a take in the video and flip to the original at the same spot
- **Status:** Built (Phases 7, 10; UX-1)
#### Use Case
- **As a** marketing video editor
- **I want to** play a take in place, picture and all, and toggle Edited / Original
- **so that** I judge whether it belongs rather than whether it sounds fine alone
#### Acceptance Criteria
- **Scenario:** Play in place
- **Given:** a line has a Ready take
- **When:** I press play on the row (or Space)
- **Then:** the player plays from a beat before the line with the take in, and the Edited / Original toggle replays the same span as shot

### User Story C2
- **Summary:** Get the continuity verdict as a sentence first, with the score behind it
- **Status:** Built (partial: prosody and audio integration are measured; voice identity and lip-sync read "not measured yet")
#### Use Case
- **As a** marketing video editor who is not an audio engineer
- **I want to** read the verdict in plain words ("sounds like him, a touch fast")
- **so that** I know what to do next without decoding a scorecard
#### Acceptance Criteria
- **Scenario:** Verdict on a take
- **Given:** a take has been voiced with a real voice
- **When:** the row shows Ready
- **Then:** the verdict is a sentence, the measured scores sit behind it, and the unmeasured dimensions say so rather than showing a number

### User Story C3
- **Summary:** Ask for another take and choose between them
- **Status:** Built (UX-1)
#### Use Case
- **As a** marketing video editor
- **I want to** ask for another take and see it beside the first
- **so that** I pick the better one rather than losing the first
#### Acceptance Criteria
- **Scenario:** Another take
- **Given:** a line has a Ready take
- **When:** I click "Another take"
- **Then:** a second take appears beside the first as a choice, each with Keep, and the first is not replaced

### User Story C4
- **Summary:** Tweak and re-hear from where the line stands, not from the original
- **Status:** Built (fix `eada8b6`)
#### Use Case
- **As a** marketing video editor iterating on a line
- **I want to** reopen the editor on the last wording and choices I tried
- **so that** each iteration is a small change, not a retype
#### Acceptance Criteria
- **Scenario:** Reopen after a take
- **Given:** I previewed a line with new words and "warmer" delivery
- **When:** I open the line's editor again
- **Then:** it shows those words and that delivery, not the original line

### User Story C5
- **Summary:** Undo anything, including a shipped line, without losing the record
- **Status:** Built (Phase 12, UX-3)
#### Use Case
- **As a** marketing video editor
- **I want to** undo a kept, moved, removed or shipped line
- **so that** no decision is final until the file leaves the tool
#### Acceptance Criteria
- **Scenario:** Undo a kept line
- **Given:** a line was kept and shows as tracked changes
- **When:** I click Undo (or press U)
- **Then:** the transcript shows the line as shot, the render skips the edit, and the edit remains in the project's history marked reverted

### User Story C6
- **Summary:** Ship the lines I am sure of and hold the rest as drafts
- **Status:** Built (UX-3)
#### Use Case
- **As a** marketing video editor under deadline
- **I want to** mark each line Keep or Hold in review
- **so that** the approved changes go out today and the doubtful ones wait without being lost
#### Acceptance Criteria
- **Scenario:** Partial ship
- **Given:** review shows three changed lines
- **When:** I mark two Keep and one Hold and click Ship it
- **Then:** the rendered file contains the two kept lines, the held line stays in the project as a draft, and each shipped line still offers Undo

---

## D · Trust and money

### User Story D1
- **Summary:** See how much the project has spent on its own, against the cap
- **Status:** Built (Phase 9b, UX-3)
#### Use Case
- **As an** account holder
- **I want to** see a small meter of spend against the project ceiling
- **so that** a session cannot run away with my vendor credit
#### Acceptance Criteria
- **Scenario:** Spend meter
- **Given:** a project has voiced several takes
- **When:** I look at the editor
- **Then:** the meter shows estimated USD spent against the ceiling and per-vendor lines on request

### User Story D2
- **Summary:** Know the cost before a plan runs and the actual cost after
- **Status:** Built (Phase 13)
#### Use Case
- **As an** account holder
- **I want to** see an estimate on the plan and the real spend on the receipt
- **so that** I can decide before paying and reconcile afterwards
#### Acceptance Criteria
- **Scenario:** Estimate then receipt
- **Given:** a plan has been made
- **When:** I read the plan and later the receipt
- **Then:** the plan shows characters, USD and seconds before Go ahead, and the receipt shows the plan's actual spend including retakes

### User Story D3
- **Summary:** Nothing is voiced or charged until I say so
- **Status:** Built (Phase 13)
#### Use Case
- **As an** account holder
- **I want to** have every paid call wait for Go ahead by default
- **so that** reading a plan never costs money
#### Acceptance Criteria
- **Scenario:** Plan under Check with me
- **Given:** autonomy is "Check with me"
- **When:** a plan is returned
- **Then:** the spend meter has moved only by the planning call, and no take exists until I click Go ahead

### User Story D4
- **Summary:** Never build on speech that was not actually said
- **Status:** Built (fix `517ace3`)
#### Use Case
- **As a** social video creator with ambient-sound footage
- **I want to** be told the clip has no words rather than shown invented lines
- **so that** I never plan, voice or pay for a change to speech that was never there
#### Acceptance Criteria
- **Scenario:** Wind-and-waves clip
- **Given:** the uploaded clip's audio track has no speech
- **When:** transcription returns
- **Then:** segments Whisper's own confidence marks as non-speech, or known invented sign-offs, are dropped, and the editor says there is nothing to change but a voice-over can be placed

### User Story D5
- **Summary:** Give consent once per project, in a sentence, at the moment it is needed
- **Status:** Built (UX-3)
#### Use Case
- **As a** marketing video editor
- **I want to** confirm I have the right to edit this speaker once, just before the first voice is made
- **so that** the gate is meaningful without being a wall on every action
#### Acceptance Criteria
- **Scenario:** First voicing
- **Given:** a project uploaded without consent
- **When:** the first take is about to be voiced
- **Then:** one sentence asks for consent, the timestamp is recorded on the project, generation proceeds, and the question never comes back on that project

### User Story D6
- **Summary:** Get a plain record of what Voltage did
- **Status:** Built (Phase 13, UX-3)
#### Use Case
- **As a** marketing video editor handing the file to a colleague
- **I want to** read a receipt of every change, retake and cost
- **so that** I can explain what was done and why
#### Acceptance Criteria
- **Scenario:** Receipt after shipping
- **Given:** a plan has run and been shipped
- **When:** I open the receipt
- **Then:** it lists every line changed, added or removed, the takes tried with their verdicts, and the spend

### User Story D7 (new)
- **Summary:** Stop new paid work at the ceiling and say why
- **Status:** Built (Phase 9b)
#### Use Case
- **As an** account holder
- **I want to** have the project refuse new paid work once it reaches its budget
- **so that** the cap is enforced, not just displayed
#### Acceptance Criteria
- **Scenario:** Budget reached
- **Given:** the project's estimated spend is at `AVE_PROJECT_BUDGET_USD` or its voice character budget is used up
- **When:** I preview another take
- **Then:** the job fails with the budget as its reason and the row says so in one sentence

---

## E · Voices

### User Story E1
- **Summary:** Hear the new line in the speaker's own voice
- **Status:** Backlog — Phase 15 (needs ElevenLabs Starter for instant cloning; the reference-audio extraction is built)
#### Use Case
- **As a** marketing video editor
- **I want to** have the new words spoken in the on-screen speaker's own voice
- **so that** the edit is indistinguishable from the original take
#### Acceptance Criteria
- **Scenario:** Cloned voice
- **Given:** consent is recorded and the speaker has enough reference speech outside the selection
- **When:** a take is voiced
- **Then:** it is in a voice cloned from that speaker, the "Stock voice" warning is gone, and voice identity is measured with SIM-o at or above 0.75

### User Story E2
- **Summary:** Give each speaker a stand-in voice until cloning lands
- **Status:** Built (Phase 11; the premade voice is a documented seam)
#### Use Case
- **As a** marketing video editor on a two-speaker clip
- **I want to** assign a premade voice to each speaker
- **so that** a line in one speaker's words is never spoken in the other's stand-in
#### Acceptance Criteria
- **Scenario:** Voice per speaker
- **Given:** two speakers are detected
- **When:** I set a voice on each and change a line of the second speaker
- **Then:** the take is in the second speaker's voice, carries the "Stock voice" warning, and continuity is measured against that speaker's own speech only

### User Story E3
- **Summary:** Perform the line myself and have it converted to the speaker
- **Status:** Backlog — Phase 15 (Voice Changer route)
#### Use Case
- **As a** social video creator who wants a specific delivery
- **I want to** record the new line in my own voice
- **so that** the timing and emotion are mine while the voice stays the speaker's
#### Acceptance Criteria
- **Scenario:** Performed take
- **Given:** the speaker has a clone
- **When:** I record the line in the row and submit it
- **Then:** the take keeps my timing and prosody in the speaker's voice and runs through the same fit and continuity checks

---

## F · Picture and fit

### User Story F1
- **Summary:** The picture keeps playing under an added line
- **Status:** Built (UX-1)
#### Use Case
- **As a** marketing video editor
- **I want to** have an added line play over the moving picture by default
- **so that** the video never freezes on a face unless I chose that
#### Acceptance Criteria
- **Scenario:** Add a line with room after it
- **Given:** there is a pause after the chosen line long enough for the new one
- **When:** the added line is voiced
- **Then:** it is layered over the pause with the picture moving, and the frame is held only when there is no room, with the row saying so

### User Story F2
- **Summary:** A line that runs long is fitted gracefully before anyone is asked
- **Status:** Built (Phase 14)
#### Use Case
- **As a** marketing video editor
- **I want to** have a long line shortened, slipped into the pause, or gently sped up on its own
- **so that** most changes just fit and I am only asked when there is nowhere to go
#### Acceptance Criteria
- **Scenario:** Take 8% too long
- **Given:** a take overruns its slot by more than 5%
- **When:** the job fits it
- **Then:** pauses are trimmed first, the line may start up to 150 ms early, another take is voiced if still long, and only when the pause cannot hold it does the row go Needs you with a shorter wording as the first option

### User Story F3
- **Summary:** The mouth matches the new words
- **Status:** Backlog — Phase 17 (lip-sync vendor; sync.so recommended)
#### Use Case
- **As a** marketing video editor
- **I want to** have the speaker's mouth move with the new words
- **so that** the edit survives a viewer watching the face
#### Acceptance Criteria
- **Scenario:** Lip-synced edit
- **Given:** a take is kept on a line where the speaker's face is on screen
- **When:** the video is rendered
- **Then:** the mouth region is re-synthesised for the edited span and LSE-D is within 1.0 of the original footage's own score

### User Story F4
- **Summary:** Choose how the new sound meets the picture
- **Status:** Built (Phase 8, UX-1, UX-2)
#### Use Case
- **As a** marketing video editor
- **I want to** choose replace, layer over, or add after, and start-at or stretch
- **so that** an added line sits where I mean it to, over music or in a gap
#### Acceptance Criteria
- **Scenario:** Line over music
- **Given:** the selection holds music and no speech
- **When:** I send "add the line 'Thirsty!' over the music"
- **Then:** the line is layered over the existing sound without replacing it, and the Sound-meets-picture control shows the choice

### User Story F5 (new)
- **Summary:** The picture flexes instead of freezing when a line needs more time
- **Status:** Backlog — Phase 16 (self-hosted RIFE)
#### Use Case
- **As a** marketing video editor
- **I want to** have the picture slowed slightly or a living hold used when a line runs long
- **so that** no edit ever ships a frozen frame while a face is on screen
#### Acceptance Criteria
- **Scenario:** Long line with a face on screen
- **Given:** a kept take needs 2 s more than its slot and there is no pause to absorb it
- **When:** the video is rendered
- **Then:** the picture is retimed by no more than 12% over the span, marked on the timeline, and no frame is held still

---

## G · Finishing and returning

### User Story G1
- **Summary:** Export a real file and share it
- **Status:** Built (partial: audio is re-voiced, video frames are the original until F3 lands)
#### Use Case
- **As a** marketing video editor
- **I want to** ship the edited video and get a download and a link
- **so that** I can hand the result to whoever asked for the change
#### Acceptance Criteria
- **Scenario:** Ship it
- **Given:** at least one line is kept
- **When:** I click Ship it
- **Then:** an MP4 that plays everywhere is rendered with the kept lines spliced in, and the ship sheet shows what is in the file, a download and a link

### User Story G2
- **Summary:** Come back later and find the project as I left it
- **Status:** Built (Phase 9a, UX-3)
#### Use Case
- **As a** marketing video editor
- **I want to** reopen a project from a list or its URL
- **so that** a change interrupted today can be finished tomorrow
#### Acceptance Criteria
- **Scenario:** Return after a restart
- **Given:** I shipped a project yesterday and the server has restarted since
- **When:** I open the project list or its `#p` URL
- **Then:** I see its frame, state (draft / shipped) and last change, and reopening restores the transcript, kept edits, chat and settings

### User Story G3
- **Summary:** Make a variant of a shipped video from the same plan
- **Status:** Built (UX-3)
#### Use Case
- **As a** marketing video editor producing regional versions
- **I want to** duplicate a project with its plan as a draft
- **so that** the 30% version becomes the 25% version in a few edits, not from scratch
#### Acceptance Criteria
- **Scenario:** Make a variant
- **Given:** a project is shipped
- **When:** I click "Make a variant" on the ship sheet
- **Then:** a new project opens on the same clip with the plan loaded as an unrun draft

### User Story G4 (new)
- **Summary:** Delete a project and with it my consent and all its media
- **Status:** Built
#### Use Case
- **As a** marketing video editor who no longer has the right to the footage
- **I want to** delete the project
- **so that** withdrawing consent removes everything, not just a flag
#### Acceptance Criteria
- **Scenario:** Delete from the start screen
- **Given:** a project exists with media and edits
- **When:** I confirm Delete
- **Then:** the project, its consent record and every stored artifact are gone, and it no longer appears in the list

---

## H · Control

### User Story H1
- **Summary:** Select exactly the span I mean on a word-level timeline
- **Status:** Built (Phases 3, 10)
#### Use Case
- **As a** marketing video editor on a longer clip
- **I want to** click, shift-click or drag across real words on a timeline that zooms and scrolls
- **so that** my selection lands on what was actually said
#### Acceptance Criteria
- **Scenario:** Drag across words
- **Given:** the editor is open with the word timeline behind "Precise"
- **When:** I drag from one word to another
- **Then:** the selection snaps to those words' Whisper timings and the span is shown as a time range

### User Story H2
- **Summary:** Move a take, a kept line, or an original line to another time without voicing again
- **Status:** Built (UX-1b, UX-1c)
#### Use Case
- **As a** marketing video editor
- **I want to** drag a take or a line of the original speech to a new start time
- **so that** placement is my call and costs nothing
#### Acceptance Criteria
- **Scenario:** Shift an original line
- **Given:** an untouched line is in the transcript
- **When:** I drag its grip up the transcript or type a new "Starts at" time
- **Then:** the line appears as its own row at the new time with its words as spoken, the room's sound is left where they were, and no voice call is made

### User Story H3
- **Summary:** Work through the transcript from the keyboard
- **Status:** Built (UX-4)
#### Use Case
- **As a** marketing video editor reviewing twenty lines
- **I want to** move, play, keep, undo and add from the keys
- **so that** a review pass takes seconds per line
#### Acceptance Criteria
- **Scenario:** Keyboard review
- **Given:** a line is focused
- **When:** I press ↓, Space, K in turn
- **Then:** focus moves to the next line, it plays in place, and its take is kept, with / putting the cursor in Voltage's box

### User Story H4 (new)
- **Summary:** Use the editor on a phone with touch
- **Status:** Built (UX-6 R-3)
#### Use Case
- **As a** social video creator reviewing on the move
- **I want to** reach every row action from a touch target on a phone
- **so that** I can approve a take without a laptop
#### Acceptance Criteria
- **Scenario:** Phone review
- **Given:** the editor is open at phone width
- **When:** I tap the row's "…" button
- **Then:** its actions open at 44 px targets, the grip is draggable by touch, and destructive actions ask twice

### User Story H5 (new)
- **Summary:** Use the editor with a screen reader
- **Status:** Built (UX-6 R-2)
#### Use Case
- **As a** marketing video editor who relies on assistive technology
- **I want to** have every row's state, progress and Voltage's replies announced
- **so that** I can run the same loop without sight
#### Acceptance Criteria
- **Scenario:** Take becomes Ready
- **Given:** a screen reader is running and a line is Working
- **When:** the take arrives
- **Then:** the row's new state is announced through a live region, the sheet traps focus and returns it on Escape, and Tab moves row to row

---

## I · Account and errors

### User Story I1
- **Summary:** Sign in with Google, see only my projects, and spend only my ceiling
- **Status:** Built behind `AVE_AUTH=google` (Phase 9c); off by default
#### Use Case
- **As a** signed-in team member on a shared Voltage
- **I want to** sign in with Google and see only my own projects
- **so that** a colleague's footage and spend are never mine, and mine never theirs
#### Acceptance Criteria
- **Scenario:** Two people on one server
- **Given:** `AVE_AUTH=google` and my email is allowed
- **When:** I sign in and open the project list
- **Then:** I see only projects I own, every write carries CSRF protection, and new paid work stops at my own `AVE_USER_BUDGET_USD`

### User Story I2
- **Summary:** Every failure is one sentence in the place it happened
- **Status:** Built (UX-6 R-4)
#### Use Case
- **As a** marketing video editor
- **I want to** read what went wrong in one plain sentence on the row, in the thread, or in the strip
- **so that** I know what to do next without reading a log
#### Acceptance Criteria
- **Scenario:** Vendor failure on a take
- **Given:** a line is Working
- **When:** the voice vendor fails after its retries
- **Then:** the row says in one sentence what failed and what I can do, a plan failure is Voltage's reply in the thread, and engine errors stay in the strip under the player

---

## What this list says about the backlog

Four stories are Backlog and all are blocked on vendor access or GPU, not on code: **E1** and **E3** (Phase 15, ElevenLabs Starter), **F3** (Phase 17, lip-sync vendor), **F5** (Phase 16, self-hosted RIFE). Two Built stories are explicitly partial until those land: **C2** (half the scorecard measured) and **G1** (audio re-voiced over original frames). Everything else in A–I is built and in `main` as of 2026-10-04.

Stories found in the code but missing from the agreed list, now added: **A4** help-me brief, **A5** sample clip, **B9** ask for wording, **B10** Just do it, **D7** budget enforcement, **F5** picture that flexes, **G4** delete and withdraw consent, **H4** touch, **H5** screen reader.

One known gap with no story and no UI: the continuity *failure* path can only be exercised by editing `VOICE` in `App.tsx` or calling the API directly (README, "The journey"). If a tester needs it, it wants a story under C.
