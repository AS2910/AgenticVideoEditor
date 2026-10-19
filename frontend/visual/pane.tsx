/* The Voltage pane at one width, for the visual test (visual/pane.visual.mjs):
   `?w=320&status=needs%20your%20go`. The thread carries the hard cases: a
   question with a 120-character option, a Hindi and a Chinese option, the
   turn-cap way through, and a 60-character file name (no spaces) in a step line. */
import { createRoot } from 'react-dom/client'
import '../src/styles/globals.css'
import { VoltagePane } from '../src/components/VoltagePane'
import type { ChatMessage, PlanQuestion } from '../src/types'

const q = new URLSearchParams(location.search)
const width = Number(q.get('w') ?? 390)
const status = q.get('status') ?? 'needs your go'

const LONG_OPTION = 'Voice the shorter middle line next turn, then add all five lines together so the fight commentary builds properly at 9 s'
const FILE = 'boxing_night_commentary_final_v3_WhatsApp_2026-10-19_235.mp4'

const messages: ChatMessage[] = [
  { role: 'user', text: 'Add commentary over the fight, two voices, building to the knockdown at https://example.com/a/very/long/reference/link/that/does/not/break', seq: 1 },
  { role: 'assistant', text: 'Read the transcript', kind: 'step', seq: 2, data: { tool: 'read_transcript', t: 1.2 } },
  { role: 'assistant', text: `Looked at ${FILE}`, kind: 'step', seq: 3, data: { tool: 'look_at_frames', t: 6.4 } },
  { role: 'assistant', text: 'Voiced “Blue goes DOWN!” with Daniel', kind: 'step', cost: 0.04, seq: 4, data: { tool: 'synthesize_take', t: 31.9 } },
  { role: 'assistant', text: 'I’ve voiced four of the five commentary lines: Daniel does the play-by-play and Charlie is the colour man. The middle line (7.1 to 10.3 s) was too long for its slot; supercalifragilisticexpialidociousbutlongerstill.', seq: 5 },
]

const question: PlanQuestion = {
  text: 'Redoing the middle line shorter (“Back to centre. Red’s stalking him now.”, about $0.04) would go over this turn’s $0.50 cap. What should I do?',
  options: ['Go ahead, allow $0.04 more', LONG_OPTION, 'चारों तैयार लाइनें अभी जोड़ दें और 7 से 10 सेकंड तक शांत रहने दें, फिर अगली बार देखें', '先把四句加进去，七到十秒保持安静，下一轮再补上中间那一句解说词', 'Let me listen first'],
  details: ['Raises this turn’s cap to $0.54 and carries on.', null, null, null, null],
  guess: LONG_OPTION, gate: false, cost_usd: null, left_usd: 0, cap_usd: 0.5,
  turn_cap: { needed_usd: 0.04, cap_usd: 0.5 },
}

createRoot(document.getElementById('root')!).render(
  <div style={{ display: 'flex', height: '100dvh' }}>
    <div id="frame" className="pane flex min-h-0 flex-col" style={{ width, height: 760 }}>
      <VoltagePane
        messages={messages}
        state={status}
        need={status === 'needs your go'}
        busy={status === 'working'}
        engine="Opus 5.5 · High"
        chips={['Brief · Boxing night promo, two commentators, British and Australian', '2 shared voices']}
        cap="Turn cap $0.50"
        question={question}
        onAnswer={() => {}}
        onSubmit={() => {}}
        sendLabel="Answer"
      />
    </div>
  </div>,
)
