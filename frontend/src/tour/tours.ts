import type { Tour } from './types'

/** The guided run on the sample ad: one real edit, nothing spent. Seven
 *  highlighted steps between a welcome and a done card. The host fires
 *  `turn-started`, `gate-shown`, `take-ready`, `heard-and-original`, `added`
 *  and `export-opened` through `useTour().notify` as the editor reaches them. */
export const guidedRun: Tour = {
  id: 'guided-run',
  remember: true,
  welcome: {
    title: 'Change what a video',
    mark: 'says.',
    body: "Make one real edit on our sample ad: seven clicks, and it's free. You can skip and replay it from Help any time.",
    primary: 'Start the tour',
    secondary: 'Skip',
  },
  steps: [
    {
      target: 'transcript-row',
      title: 'Voltage has read the clip',
      body: 'One line, one speaker, said at the time shown. This is what you can change.',
      action: 'Next',
      advanceOn: 'click',
    },
    {
      target: 'composer',
      title: 'Tell Voltage what the video should say',
      body: 'We put a goal in the box for you: make the offer 30% off. Send it, or write your own.',
      hint: '→ Click Send',
      action: 'Send',
      advanceOn: { event: 'turn-started' },
    },
    {
      target: 'trace',
      title: 'Watch it work',
      body: 'Every step Voltage takes, and what it costs, streams in here as it happens.',
      hint: 'Moves on when Voltage asks',
      action: 'Next',
      advanceOn: { event: 'gate-shown' },
    },
    {
      target: 'gate',
      title: 'Nothing is voiced or spent until you say go',
      body: 'Past your spending limit, Voltage asks once, on one card like this. Say go to voice it.',
      hint: '→ Click Go ahead',
      action: 'Go ahead',
      advanceOn: { event: 'take-ready' },
    },
    {
      targets: ['proposal-row', 'playback-switch'],
      title: 'Hear it in the video, then without it',
      body: 'Play the new line in place, then turn off Hear changes at the top (or press O) to hear the clip as shot.',
      hint: '→ Click Hear it, then Hear changes',
      action: 'Hear it',
      advanceOn: { event: 'heard-and-original' },
    },
    {
      target: 'add-it',
      title: "Nothing is in the video until you add it",
      body: 'Proposals stay out of the video until you add them. You can take it out again any time, even after export.',
      hint: '→ Click Add it, or press K',
      action: 'Add it',
      advanceOn: { event: 'added' },
    },
    {
      target: 'export',
      title: 'Export the file',
      body: 'Render an MP4 you can download and share, or make a variant.',
      hint: '→ Click Export',
      action: 'Export',
      advanceOn: { event: 'export-opened' },
    },
  ],
  done: {
    tag: 'Tour complete · nothing spent',
    title: 'You changed what a video',
    mark: 'says.',
    body: 'Now try your own clip. Your get-started checklist sits at the bottom left, and Help has everything else.',
    primary: 'Upload a video',
    primaryHref: '#home',
    secondary: 'Replay',
  },
}

/** The short "Show me" tours, on whatever project is open. */
export const showMe: Record<'goal' | 'add' | 'export' | 'save-voice' | 'autonomy', Tour> = {
  goal: {
    id: 'goal',
    steps: [
      { target: 'composer', title: 'Say what should change', body: 'Write the goal in your own words: a new offer, a shorter line, a voice-over. Each message starts a turn.', hint: '→ Click Send', action: 'Send', advanceOn: { event: 'turn-started' } },
      { target: 'trace', title: 'Voltage shows its work', body: 'Each step, its time and its cost appear here as it goes. It asks before anything paid.', action: 'Done', advanceOn: 'click' },
    ],
  },
  add: {
    id: 'add',
    steps: [
      { target: 'proposal-row', title: 'A proposal is not in the video yet', body: 'Hear it in place first. The words with the highlighter are the new ones.', action: 'Next', advanceOn: 'click' },
      { target: 'add-it', title: 'Add it when it sounds right', body: 'Add it puts the line in the video. Take it out again any time, even after export.', hint: '→ Click Add it, or press K', action: 'Add it', advanceOn: { event: 'added' } },
    ],
  },
  export: {
    id: 'export',
    steps: [
      { target: 'playback-switch', title: 'Hear changes plays what you will get', body: 'With Hear changes on, the player plays your changes. Off, it plays the video as shot.', action: 'Next', advanceOn: 'click' },
      { target: 'export', title: 'Export renders the file', body: 'An MP4 with everything you added, ready to download or share. Proposals you did not add stay out.', hint: '→ Click Export', action: 'Export', advanceOn: { event: 'export-opened' } },
    ],
  },
  'save-voice': {
    id: 'save-voice',
    steps: [
      { target: 'voices-made', title: 'Voices made here', body: 'Every voice Voltage cloned or designed in a project is listed with the project it came from.', action: 'Next', advanceOn: 'click' },
      { target: 'keep-voice', title: 'Keep it in your voices', body: 'A kept voice works in every project. Ask for it by name, like "use Diwali Narrator".', hint: '→ Click Keep in my voices', action: 'Keep it', advanceOn: { event: 'voice-kept' } },
    ],
  },
  autonomy: {
    id: 'autonomy',
    steps: [
      { target: 'autonomy', title: 'How much Voltage may do', body: 'Check with me voices small changes under your limit and asks before anything bigger. Just do it voices and fixes on its own, inside your turn cap.', hint: '→ Open the sheet', action: 'Open it', advanceOn: { event: 'autonomy-opened' } },
      { target: 'autonomy-sheet', title: 'Choose, and keep the asks you want', body: 'Under Just do it, exporting, cloning and designing a voice can still ask first.', action: 'Done', advanceOn: 'click' },
    ],
  },
}

export const tourById = (id: string): Tour | null => (id === guidedRun.id ? guidedRun : (showMe as Record<string, Tour>)[id] ?? null)
