import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { ProjectRule, RuleData, RuleKind } from '../types'
import { addRule, deleteRule, deleteRuleAudio, listRules, ruleAudioUrl, uploadRuleAudio } from '../api'
import { said } from './fmt'

const inputClass = 'h-8 min-w-0 rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

/** A3: the project's words. How each term is said (with a respelling the
 *  voice is sent, and an optional clip of it said right), the words no video
 *  says, and the lines every video carries. Voltage reads them in every turn
 *  and checks each take against them before it is offered. */
const LANG_WORDS: Record<string, string> = { hi: 'Hindi', hinglish: 'Hinglish', ta: 'Tamil', mr: 'Marathi', en: 'English' }

/** `languages` (B2, projects.batch): a word can be a brand name that never translates, or say how it goes in one language. */
export function ProjectWords({ projectId, languages = false }: { projectId: string; languages?: boolean }) {
  const [rules, setRules] = useState<ProjectRule[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [word, setWord] = useState({ term: '', say: '', respell: '', brand: false, lang: '', translation: '' })
  const [banned, setBanned] = useState('')
  const [line, setLine] = useState('')
  const clipFor = useRef<number | null>(null)
  const clipInput = useRef<HTMLInputElement>(null)

  const load = () => {
    setError(null)
    listRules(projectId).then(setRules).catch((e) => setError(said(e, 'Could not read the project words.')))
  }
  useEffect(load, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (key: string, fn: () => Promise<void>, fallback: string) => {
    setBusy(key)
    setNote(null)
    try { await fn() } catch (e) { setNote(said(e, fallback)) } finally { setBusy(null) }
  }
  const add = (kind: RuleKind, data: RuleData, done: () => void) => act(`add-${kind}`, async () => {
    const made = await addRule(projectId, kind, data)
    setRules((r) => [...(r ?? []), made])
    done()
  }, 'Could not add that.')
  const remove = (rule: ProjectRule) => act(`rule-${rule.rule_id}`, async () => {
    await deleteRule(projectId, rule.rule_id)
    setRules((r) => (r ?? []).filter((x) => x.rule_id !== rule.rule_id))
  }, 'Could not remove that.')
  const swap = (next: ProjectRule) => setRules((r) => (r ?? []).map((x) => (x.rule_id === next.rule_id ? next : x)))
  const pickClip = (ruleId: number) => { clipFor.current = ruleId; clipInput.current?.click() }
  const uploadClip = (file: File | undefined) => {
    const ruleId = clipFor.current
    if (!file || ruleId === null) return
    void act(`clip-${ruleId}`, async () => swap(await uploadRuleAudio(projectId, ruleId, file)), 'Could not keep that clip.')
  }
  const dropClip = (rule: ProjectRule) => act(`clip-${rule.rule_id}`, async () => swap(await deleteRuleAudio(projectId, rule.rule_id)), 'Could not remove the clip.')

  const submitWord = (e: FormEvent) => {
    e.preventDefault()
    if (!word.term.trim() || !word.say.trim()) return
    void add('pronounce', {
      term: word.term.trim(), say: word.say.trim(), ...(word.respell.trim() ? { respell: word.respell.trim() } : {}),
      ...(languages && word.brand ? { brand: true } : {}),
      ...(languages && !word.brand && word.lang && word.translation.trim() ? { lang: word.lang, translation: word.translation.trim() } : {}),
    }, () => setWord({ term: '', say: '', respell: '', brand: false, lang: '', translation: '' }))
  }
  const submitBanned = (e: FormEvent) => { e.preventDefault(); if (banned.trim()) void add('banned', { word: banned.trim() }, () => setBanned('')) }
  const submitLine = (e: FormEvent) => { e.preventDefault(); if (line.trim()) void add('required_line', { text: line.trim() }, () => setLine('')) }

  const of = (kind: RuleKind) => (rules ?? []).filter((r) => r.kind === kind)
  const words = of('pronounce'), bans = of('banned'), lines = of('required_line')

  return (
    <section aria-label="Words" className="rise flex flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="words" data-tour="project-words">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-xl font-bold">Words</h2>
        <span className="tag text-faint">Voltage says these the project's way and checks every take</span>
      </div>
      <input ref={clipInput} className="sr-only" type="file" accept="audio/*,video/webm" aria-label="Choose a clip of the word said right" tabIndex={-1}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; uploadClip(f) }} />
      {error && (
        <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
          <span className="flex-1">{error}</span><button type="button" className="btn sm" onClick={load}>Try again</button>
        </div>
      )}
      {!error && rules === null && <p className="m-0 text-sm text-muted-foreground" role="status">Reading the project words…</p>}
      {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}
      {rules !== null && (
        <>
          <div className="flex flex-col gap-1.5">
            {words.length === 0 ? (
              <p className="m-0 text-[13px] text-muted-foreground">No words yet. Add a brand or a name and how it is said; select a word in any video's transcript to add it from there.</p>
            ) : (
              <div className="-mx-1 overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse text-sm">
                  <thead>
                    <tr className="text-left">
                      {['Term', 'How to say it', 'Respell', 'Example audio', ''].map((h, k) => <th key={k} scope="col" className="tag px-1 pb-1.5 font-normal text-faint">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {words.map((r) => (
                      <tr key={r.rule_id} className="border-t border-line align-middle" data-testid="word-row">
                        <td className="px-1 py-2 font-semibold">{r.data.term}
                          {languages && r.data.brand && <span className="stamp in ml-1.5 whitespace-nowrap" title="Never translated in a language version">Brand</span>}
                          {languages && r.data.lang && r.data.translation && <span className="ml-1.5 block text-[13px] font-normal text-muted-foreground">{LANG_WORDS[r.data.lang] ?? r.data.lang}: {r.data.translation}</span>}
                        </td>
                        <td className="px-1 py-2">{r.data.say}</td>
                        <td className="px-1 py-2 text-muted-foreground">{r.data.respell ?? <span className="text-faint">None</span>}</td>
                        <td className="px-1 py-2">
                          {busy === `clip-${r.rule_id}` ? <span className="text-[13px] text-muted-foreground" role="status">Saving the clip…</span> : r.data.audio ? (
                            <span className="flex items-center gap-2">
                              <audio className="h-8 max-w-[160px]" controls preload="none" src={ruleAudioUrl(projectId, r.rule_id, r.data.audio)} aria-label={`How ${r.data.term} is said`} />
                              <button type="button" className="act" onClick={() => void dropClip(r)} aria-label={`Remove the clip for ${r.data.term}`}>Remove</button>
                            </span>
                          ) : (
                            <button type="button" className="act" onClick={() => pickClip(r.rule_id)} disabled={busy !== null}>Add a clip</button>
                          )}
                        </td>
                        <td className="px-1 py-2 text-right">
                          <button type="button" className="act" onClick={() => void remove(r)} disabled={busy !== null} aria-label={`Remove ${r.data.term}`}>Remove</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <form className="flex flex-wrap items-center gap-2" onSubmit={submitWord} aria-label="Add a word">
              <input className={`${inputClass} flex-[1_1_120px]`} placeholder="Term, e.g. Bhaji Cam" aria-label="Term" value={word.term} onChange={(e) => setWord({ ...word, term: e.target.value })} />
              <input className={`${inputClass} flex-[1_1_120px]`} placeholder="How to say it" aria-label="How to say it" value={word.say} onChange={(e) => setWord({ ...word, say: e.target.value })} />
              <input className={`${inputClass} flex-[1_1_120px]`} placeholder="Respell (optional)" aria-label="Respell" value={word.respell} onChange={(e) => setWord({ ...word, respell: e.target.value })} />
              {languages && (
                <span className="flex w-full flex-wrap items-center gap-2" data-testid="word-languages">
                  <label className="flex min-h-8 items-center gap-1.5 text-sm"><input type="checkbox" className="size-4" checked={word.brand} onChange={(e) => setWord({ ...word, brand: e.target.checked })} />Brand name, never translate</label>
                  {!word.brand && (
                    <>
                      <select className={`${inputClass} flex-[0_1_140px]`} aria-label="In language" value={word.lang} onChange={(e) => setWord({ ...word, lang: e.target.value })}>
                        <option value="">Any language</option>
                        {Object.entries(LANG_WORDS).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                      </select>
                      {word.lang && <input className={`${inputClass} flex-[1_1_140px]`} placeholder="Translation" aria-label="Translation" value={word.translation} onChange={(e) => setWord({ ...word, translation: e.target.value })} />}
                    </>
                  )}
                </span>
              )}
              <button type="submit" className="btn sm" disabled={!word.term.trim() || !word.say.trim() || busy !== null}>{busy === 'add-pronounce' ? 'Adding…' : '+ Add word'}</button>
            </form>
          </div>

          <div className="flex flex-col gap-1.5 border-t-[1.5px] border-line pt-3" data-testid="banned-words">
            <span className="disp text-base font-bold">Banned words</span>
            {bans.length === 0 ? <p className="m-0 text-[13px] text-muted-foreground">None. A take Voltage writes with one is marked and not offered; a line you type with one is only warned about.</p> : (
              <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                {bans.map((r) => (
                  <li key={r.rule_id} className="inline-flex h-8 items-center gap-1 rounded-full border-[1.5px] border-line2 pr-1 pl-3 text-sm">
                    {r.data.word}
                    <button type="button" className="act px-1.5" onClick={() => void remove(r)} disabled={busy !== null} aria-label={`Remove ${r.data.word}`}>×</button>
                  </li>
                ))}
              </ul>
            )}
            <form className="flex flex-wrap items-center gap-2" onSubmit={submitBanned} aria-label="Add a banned word">
              <input className={`${inputClass} flex-[1_1_200px]`} placeholder="A word no video says" aria-label="Banned word" value={banned} onChange={(e) => setBanned(e.target.value)} />
              <button type="submit" className="btn sm" disabled={!banned.trim() || busy !== null}>{busy === 'add-banned' ? 'Adding…' : '+ Add'}</button>
            </form>
          </div>

          <div className="flex flex-col gap-1.5 border-t-[1.5px] border-line pt-3" data-testid="required-lines">
            <span className="disp text-base font-bold">Required lines</span>
            {lines.length === 0 ? <p className="m-0 text-[13px] text-muted-foreground">None. Add a line every video carries, like “T&C apply”.</p> : lines.map((r) => (
              <div key={r.rule_id} className="flex items-center gap-2.5 border-t border-line py-1.5 first:border-t-0">
                <span className="flex-1">“{r.data.text}”</span>
                <button type="button" className="act" onClick={() => void remove(r)} disabled={busy !== null} aria-label={`Remove the line ${r.data.text}`}>Remove</button>
              </div>
            ))}
            <form className="flex flex-wrap items-center gap-2" onSubmit={submitLine} aria-label="Add a required line">
              <input className={`${inputClass} flex-[1_1_200px]`} placeholder="A line every video carries" aria-label="Required line" value={line} onChange={(e) => setLine(e.target.value)} />
              <button type="submit" className="btn sm" disabled={!line.trim() || busy !== null}>{busy === 'add-required_line' ? 'Adding…' : '+ Add'}</button>
            </form>
          </div>
        </>
      )}
    </section>
  )
}
