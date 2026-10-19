import { useEffect, useId, useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent } from 'react'
import type { CloneableSpeaker, DesignedPreview, MadeVoice, MyVoice, Voice, ProjectVoice } from '../types'
import type { Me } from '../api'
import {
  cloneSpeakerToMine, deleteMyVoice, designVoicePreviews, keepDesignedVoice, keepVoice,
  listCloneableSpeakers, listMadeVoices, listVoices, uploadMyVoice, voiceSampleUrl,
} from '../api'
import { cn } from '@/lib/utils'
import { useOnboarding } from '../guides/onboarding'
import { useTour } from '../tour/engine'
import { hrefFor } from '../lib/route'
import { Bolt, PlayGlyph, Shell, StopGlyph } from './Shell'
import { barsFor, firstName, said, whenLabel } from './fmt'

type Tab = 'all' | 'yours' | 'project' | 'catalogue'
type Way = 'record' | 'describe' | 'clone'
type Kind = NonNullable<MyVoice['kind']>
const KIND_WORD: Record<Kind, string> = { recorded: 'Recorded', designed: 'Designed', library: 'Library', cloned: 'Cloned' }
const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'yours', label: 'Yours' }, { key: 'project', label: 'In projects' }, { key: 'catalogue', label: 'Catalogue' },
]
const WAYS: { key: Way; h: string; d: string }[] = [
  { key: 'record', h: 'Record or upload', d: 'Your voice, or anyone who said yes' },
  { key: 'describe', h: 'Describe it', d: 'Voltage designs it from words' },
  { key: 'clone', h: 'From a project speaker', d: 'Keep someone from a clip' },
]
const cap = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

/** Arrow keys walk a row of tabs or radios and pick as they go. */
function walk(e: KeyboardEvent<HTMLElement>, selector: string, pick: (el: HTMLElement) => void) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return
  e.preventDefault()
  const all = Array.from(e.currentTarget.parentElement?.querySelectorAll<HTMLElement>(selector) ?? [])
  const i = all.indexOf(e.currentTarget)
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1
    : (i + (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1) + all.length) % all.length
  const el = all[next]
  if (el) { el.focus(); pick(el) }
}

function HearButton({ url, name, playing, onToggle, className, size = 34, glyph = 12 }: {
  url: string; name: string; playing: string | null; onToggle: (url: string) => void; className?: string; size?: number; glyph?: number
}) {
  const on = playing === url
  return (
    <button type="button" className={cn('btn volt sm shrink-0 p-0 shadow-none', className)} style={{ width: size, height: size }} aria-label={`${on ? 'Stop' : 'Hear'} ${name}`} aria-pressed={on} onClick={() => onToggle(url)}>
      {on ? <StopGlyph size={glyph} /> : <PlayGlyph size={glyph} />}
    </button>
  )
}

const Wave = ({ busy }: { busy?: boolean }) => (
  <span className={cn('wave', busy && 'busy')} aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /></span>
)

interface VoicesPageProps { me: Me | null }

/** Your voices: kept across projects, made inside one, and the catalogue; and on the
 *  black pane, three ways to add one to keep. */
export function VoicesPage({ me }: VoicesPageProps) {
  const onboarding = useOnboarding()
  const tour = useTour()
  /** A voice is now yours: the checklist's Save a voice is done, and a Show me tour waiting on it moves on. */
  const voiceIsYours = () => { onboarding.markChecklist('save-voice'); tour.notify('voice-kept') }
  const uid = useId()
  const [tab, setTab] = useState<Tab>('all')
  const [mine, setMine] = useState<MyVoice[]>([])
  const [catalogue, setCatalogue] = useState<Voice[]>([])
  const [slots, setSlots] = useState<{ used: number; limit: number } | null>(null)
  const [made, setMade] = useState<MadeVoice[]>([])
  // Folders (2026-10-19): voices shared in one of your projects, between the video's and yours.
  const [inProject, setInProject] = useState<ProjectVoice[]>([])
  const [speakers, setSpeakers] = useState<CloneableSpeaker[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  // One <audio> for every sample on the page.
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  const toggle = (url: string) => {
    const a = audio.current
    if (!a) return
    if (playing === url) { a.pause(); setPlaying(null); return }
    a.src = url
    const p = a.play()
    setPlaying(url)
    if (p && typeof p.catch === 'function') p.catch(() => setPlaying(null))
  }

  useEffect(() => {
    let live = true
    Promise.allSettled([listVoices(), listMadeVoices(), listCloneableSpeakers()]).then(([v, m, s]) => {
      if (!live) return
      if (v.status === 'fulfilled') {
        setMine(v.value.mine ?? [])
        setInProject(v.value.project ?? [])
        setCatalogue(v.value.voices.filter((x) => x.category !== 'mine'))
        setSlots(v.value.slots ?? null)
      } else setLoadError(said(v.reason, 'Your voices could not be read.'))
      if (m.status === 'fulfilled') setMade(m.value.voices)
      if (s.status === 'fulfilled') setSpeakers(s.value.speakers)
      setLoaded(true)
    })
    return () => { live = false }
  }, [])

  // Cards: the ••• menu and the remove confirm.
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [busyVoice, setBusyVoice] = useState<string | null>(null)
  const remove = async (v: MyVoice) => {
    setBusyVoice(v.voice_id); setListError(null)
    try {
      await deleteMyVoice(v.voice_id)
      setMine((m) => m.filter((x) => x.voice_id !== v.voice_id))
      setSlots((s) => (s ? { ...s, used: Math.max(0, s.used - 1) } : s))
      setRemoving(null)
    } catch (e) { setListError(said(e, `${v.name} could not be removed.`)) } finally { setBusyVoice(null) }
  }
  const kept = (v: MyVoice) => {
    setMine((m) => [v, ...m.filter((x) => x.voice_id !== v.voice_id)])
    setSlots((s) => (s ? { ...s, used: s.used + 1 } : s))
  }
  const keep = async (mv: MadeVoice) => {
    setBusyVoice(mv.voice_id); setListError(null)
    try {
      const v = await keepVoice(mv.voice_id)
        voiceIsYours()
      kept(v)
      setMade((all) => all.map((x) => (x.voice_id === mv.voice_id ? { ...x, kept: true } : x)))
    } catch (e) { setListError(said(e, `${mv.name} could not be kept.`)) } finally { setBusyVoice(null) }
  }

  // The pane: one form, three ways in.
  const [way, setWay] = useState<Way>('record')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [recName, setRecName] = useState(firstName(me) ?? '')
  const [desc, setDesc] = useState('')
  const [descName, setDescName] = useState('')
  const [previews, setPreviews] = useState<DesignedPreview[] | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const [speakerKey, setSpeakerKey] = useState('')
  const [cloneName, setCloneName] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const [fileOver, setFileOver] = useState(false)

  // Recording, where the browser can.
  const canRecord = typeof window !== 'undefined' && 'MediaRecorder' in window && typeof navigator.mediaDevices?.getUserMedia === 'function'
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const tick = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => () => {
    if (tick.current) clearInterval(tick.current)
    const r = recorder.current
    if (r && r.state !== 'inactive') { r.stream.getTracks().forEach((t) => t.stop()); r.stop() }
    audio.current?.pause()
  }, [])
  const startRecording = async () => {
    setFormError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunks.current = []
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.current.push(e.data) }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        if (tick.current) clearInterval(tick.current)
        tick.current = null
        setFile(new File(chunks.current, 'recording.webm', { type: rec.mimeType || 'audio/webm' }))
        setRecording(false)
      }
      recorder.current = rec
      rec.start()
      setElapsed(0)
      setRecording(true)
      tick.current = setInterval(() => setElapsed((s) => s + 1), 1000)
    } catch (e) { setFormError(said(e, 'The microphone could not be opened.')) }
  }
  const stopRecording = () => recorder.current?.stop()
  const tookFile = (files: FileList | null) => { const f = files?.[0]; if (f) { setFile(f); setFormError(null) } }

  const speaker = speakers.find((s) => `${s.video_id}:${s.label}` === speakerKey) ?? null
  const pickSpeaker = (key: string) => {
    setSpeakerKey(key)
    const s = speakers.find((x) => `${x.video_id}:${x.label}` === key)
    if (s && (cloneName.trim() === '' || cloneName === speaker?.name)) setCloneName(s.name)
  }
  useEffect(() => { if (!speakerKey && speakers[0]) { setSpeakerKey(`${speakers[0].video_id}:${speakers[0].label}`); setCloneName((n) => n || speakers[0].name) } }, [speakers, speakerKey])

  const cta = way === 'record'
    ? { label: 'Clone and keep', cost: 'free · 1 slot', ready: file !== null && recName.trim() !== '' }
    : way === 'describe'
      ? previews
        ? { label: `Keep as ${descName.trim() || '…'}`, cost: 'free · 1 slot', ready: chosen !== null && descName.trim() !== '' }
        : { label: 'Design 3 previews', cost: '~$0.06 · 1 slot', ready: desc.trim() !== '' }
      : { label: 'Clone and keep', cost: 'free · 1 slot', ready: speaker !== null && cloneName.trim() !== '' }
  const canGo = cta.ready && consent && !busy

  const submit = async () => {
    if (!canGo) return
    setBusy(true); setFormError(null); setNote(null)
    try {
      if (way === 'record' && file) {
        const v = await uploadMyVoice(recName.trim(), file)
        voiceIsYours()
        kept(v); setFile(null); setNote(`Kept ${v.name} in your voices.`)
      } else if (way === 'describe' && !previews) {
        const r = await designVoicePreviews(desc.trim())
        setPreviews(r.previews); setChosen(null)
      } else if (way === 'describe' && previews) {
        const p = previews.find((x) => x.generated_voice_id === chosen)
        if (!p) return
        const v = await keepDesignedVoice(p.generated_voice_id, descName.trim(), p.sha256, desc.trim())
        voiceIsYours()
        kept(v); setPreviews(null); setChosen(null); setDesc(''); setDescName(''); setNote(`Kept ${v.name} in your voices.`)
      } else if (way === 'clone' && speaker) {
        const v = await cloneSpeakerToMine(speaker.video_id, speaker.label, cloneName.trim())
        voiceIsYours()
        kept(v); setNote(`Kept ${v.name} in your voices.`)
      }
    } catch (e) { setFormError(said(e, 'That did not work.')) } finally { setBusy(false) }
  }

  const showYours = tab === 'all' || tab === 'yours'
  const showProject = tab === 'all' || tab === 'project'
  const showCatalogue = tab === 'all' || tab === 'catalogue'
  const counts: Record<Tab, number | null> = { all: null, yours: mine.length, project: made.length, catalogue: catalogue.length }
  const field = 'h-[42px] rounded-lg border-[1.5px] border-pline bg-psunk px-3 text-[15px] text-ptext outline-none focus-visible:border-volt'
  const right = slots ? <span className="tag text-muted-foreground">Voice slots <span className="tnum font-semibold text-foreground">{slots.used}</span> / {slots.limit}</span> : null

  return (
    <Shell active="voices" me={me} right={right} mainClassName="flex flex-wrap">
      <audio ref={audio} onEnded={() => setPlaying(null)} onError={() => setPlaying(null)} />
      <section className="min-w-0 flex-[999_1_640px] px-4 pt-8 pb-16 sm:px-8 sm:pt-10 sm:pb-[72px]">
        <div className="mx-auto flex max-w-[900px] flex-col gap-9">
          <div className="flex flex-col gap-2">
            <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Voices</h1>
            <p className="m-0 text-base text-muted-foreground">Save a voice once, and Voltage can use it in any project. Just say “in my voice” or “use Goa Narrator”.</p>
          </div>

          <div role="tablist" aria-label="Which voices" className="segs flex-wrap self-start">
            {TABS.map((t) => (
              <button
                key={t.key} id={`${uid}-tab-${t.key}`} role="tab" type="button" className="seg"
                aria-selected={tab === t.key} aria-controls={`${uid}-panel`} tabIndex={tab === t.key ? 0 : -1}
                onClick={() => setTab(t.key)}
                onKeyDown={(e) => walk(e, '[role="tab"]', (el) => setTab(el.id.slice(`${uid}-tab-`.length) as Tab))}
              >
                {t.label}{loaded && counts[t.key] !== null ? ` · ${counts[t.key]}` : ''}
              </button>
            ))}
          </div>

          {!loaded ? (
            <p className="m-0 min-h-[200px] text-muted-foreground" role="status">Fetching your voices…</p>
          ) : (
            <div id={`${uid}-panel`} role="tabpanel" aria-labelledby={`${uid}-tab-${tab}`} className="flex flex-col gap-9">
              {loadError && <p className="m-0 text-sm text-destructive" role="alert">{loadError}</p>}
              {listError && <p className="m-0 text-sm text-destructive" role="alert">{listError}</p>}

              {showYours && (
                <section className="flex flex-col gap-3.5" aria-labelledby={`${uid}-yours`}>
                  <div className="flex items-baseline gap-2.5"><h2 id={`${uid}-yours`} className="disp m-0 text-2xl font-bold">Yours</h2><span className="tag text-faint">kept across projects</span></div>
                  {mine.length === 0 ? (
                    <p className="m-0 text-muted-foreground">No voice of yours yet. Add one on the right, and it is there in every project.</p>
                  ) : (
                    <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4 p-0">
                      {mine.map((v, i) => {
                        const kind: Kind = v.kind ?? 'recorded'
                        const sample = v.sample_sha ? voiceSampleUrl(v.sample_sha) : null
                        const used = v.used_in && v.used_in > 0 ? `Used in ${v.used_in} ${v.used_in === 1 ? 'project' : 'projects'}` : `Saved · ${whenLabel(v.at)}`
                        const desc = v.description ?? (kind === 'recorded' ? `Your own voice, from a ${Math.round(v.seconds)} s recording` : '')
                        return (
                          <li key={v.voice_id} className="vcard group/v rise relative flex flex-col gap-3.5 p-[18px] transition-all duration-200 hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-ink" style={{ animationDelay: `${Math.min(i, 5) * 100}ms` }} aria-busy={busyVoice === v.voice_id || undefined}>
                            <div className="relative flex items-center gap-2.5">
                              <span className={cn('stamp', kind !== 'recorded' && 'inkd')}>{KIND_WORD[kind]}</span>
                              <span className="flex-1" />
                              <button type="button" className="act" aria-label={`More for ${v.name}`} aria-haspopup="menu" aria-expanded={menuFor === v.voice_id} onClick={() => setMenuFor(menuFor === v.voice_id ? null : v.voice_id)} onKeyDown={(e) => { if (e.key === 'Escape') setMenuFor(null) }}>•••</button>
                              {menuFor === v.voice_id && (
                                <div role="menu" aria-label={`For ${v.name}`} className="absolute top-full right-0 z-10 mt-1 min-w-36 rounded-lg border-[1.5px] border-foreground bg-card p-1 shadow-ink">
                                  <button type="button" role="menuitem" className="act w-full justify-start text-destructive" onClick={() => { setMenuFor(null); setRemoving(v.voice_id) }}>Remove…</button>
                                </div>
                              )}
                            </div>
                            <div className="flex h-9 items-center gap-[3px]" aria-hidden="true">
                              {barsFor(v.voice_id).map((h, b) => (
                                <span key={b} className="w-1 origin-center rounded-sm bg-foreground motion-safe:group-hover/v:animate-[wv_.9s_ease-in-out_infinite]" style={{ height: h, animationDelay: `${(b % 3) * 150}ms` }} />
                              ))}
                            </div>
                            <div className="flex flex-col gap-1">
                              <span className="disp text-[22px] font-bold">{v.name}</span>
                              {desc && <span className="text-[13px] text-muted-foreground">{desc}</span>}
                            </div>
                            {removing === v.voice_id ? (
                              <div className="flex flex-col gap-2 text-[13px] text-muted-foreground" role="group" aria-label={`Remove ${v.name}?`}>
                                <span>Remove <strong className="font-semibold text-foreground">{v.name}</strong>? Deleting the voice withdraws its consent; projects keep the takes already made.</span>
                                <span className="flex gap-2">
                                  <button type="button" className="btn sm" onClick={() => setRemoving(null)} autoFocus>Keep</button>
                                  <button type="button" className="btn sm border-destructive text-destructive" onClick={() => void remove(v)} disabled={busyVoice === v.voice_id}>{busyVoice === v.voice_id ? 'Removing…' : 'Remove'}</button>
                                </span>
                              </div>
                            ) : (
                              <div className="flex items-center gap-2">
                                {sample && <HearButton url={sample} name={v.name} playing={playing} onToggle={toggle} />}
                                <span className="tag text-faint">{used}</span>
                              </div>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </section>
              )}

              {showProject && inProject.length > 0 && (
                <section className="flex flex-col gap-3.5" aria-labelledby={`${uid}-shared`} data-testid="in-project">
                  <div className="flex flex-wrap items-baseline gap-2.5"><h2 id={`${uid}-shared`} className="disp m-0 text-2xl font-bold">In a project</h2><span className="tag text-faint">shared with every video there</span></div>
                  {inProject.map((pv) => (
                    <div key={`${pv.project_id}:${pv.voice_id}`} className="rise grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 rounded-[10px] border border-line bg-card px-3.5 py-3">
                      <span className="stamp in">{pv.kind ? (KIND_WORD as Record<string, string>)[pv.kind] ?? pv.kind : 'Shared'}</span>
                      <div className="flex min-w-0 flex-col">
                        <span className="disp text-base font-semibold">{pv.name}</span>
                        <span className="text-[13px] text-muted-foreground">{pv.description ?? 'Ask for it by name in any video of the project.'}</span>
                      </div>
                      <a href={hrefFor({ page: 'folder', projectId: pv.project_id ?? '' })} className="tag text-foreground no-underline">{pv.project_name ?? 'the project'} →</a>
                    </div>
                  ))}
                </section>
              )}
              {showProject && (
                <section className="flex flex-col gap-3.5" aria-labelledby={`${uid}-made`} data-tour="voices-made">
                  <div className="flex flex-wrap items-baseline gap-2.5"><h2 id={`${uid}-made`} className="disp m-0 text-2xl font-bold">Made inside a project</h2><span className="tag text-faint">deleted with the project unless you keep them</span></div>
                  {made.length === 0 ? (
                    <p className="m-0 text-muted-foreground">Nothing yet. A voice Voltage designs or clones inside a project shows here, with a way to keep it.</p>
                  ) : made.map((mv, mi) => (
                    <div key={mv.voice_id} className="rise grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3.5 rounded-[10px] border border-line bg-card px-3.5 py-3 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
                      <span className="stamp in">{KIND_WORD[mv.kind]}</span>
                      <div className="flex min-w-0 flex-col">
                        <span className="disp text-base font-semibold">{mv.name} <span className="tag font-normal text-faint">· {mv.filename}</span></span>
                        {mv.description && <span className="text-[13px] text-muted-foreground">{mv.description}</span>}
                      </div>
                      {mv.kept
                        ? <button type="button" className="btn sm col-span-2 justify-self-start sm:col-span-1" disabled aria-disabled="true">✓ Kept in yours</button>
                        : <button type="button" className="btn volt sm col-span-2 justify-self-start sm:col-span-1" data-tour={mi === made.findIndex((x) => !x.kept) ? 'keep-voice' : undefined} onClick={() => void keep(mv)} disabled={busyVoice === mv.voice_id}>{busyVoice === mv.voice_id ? 'Keeping…' : 'Keep in my voices'}</button>}
                    </div>
                  ))}
                </section>
              )}

              {showCatalogue && (
                <section className="flex flex-col gap-3.5" aria-labelledby={`${uid}-cat`}>
                  <div className="flex items-baseline gap-2.5"><h2 id={`${uid}-cat`} className="disp m-0 text-2xl font-bold">Catalogue</h2><span className="tag text-faint">{catalogue.length} voices · Voltage browses these first</span></div>
                  {catalogue.length === 0 ? <p className="m-0 text-muted-foreground">The catalogue is empty on this server.</p> : (
                    <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                      {catalogue.map((c) => (
                        <li key={c.voice_id} className="inline-flex h-9 items-center gap-2 rounded-full border border-line2 bg-card pr-3 pl-1.5 text-[13px] transition-all duration-150 hover:-translate-y-0.5 hover:border-foreground">
                          {c.preview_url
                            ? <HearButton url={c.preview_url} name={c.name} playing={playing} onToggle={toggle} className="volt-none rounded-full" size={26} glyph={9} />
                            : <span className="inline-block size-[26px] rounded-full border border-line2" aria-hidden="true" />}
                          {c.name}
                          {c.accent && <span className="tag text-faint">{cap(c.accent)}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </div>
          )}
        </div>
      </section>

      <aside className="pane flex min-w-0 flex-[1_1_380px] flex-col gap-[22px] px-6 py-8" aria-labelledby={`${uid}-new`} aria-busy={busy || undefined}>
        <div className="flex flex-col gap-1.5">
          <span className="tag text-volt">+ New voice</span>
          <h2 id={`${uid}-new`} className="disp m-0 text-[28px] font-bold">Add a voice to keep</h2>
        </div>

        <div role="radiogroup" aria-label="How to make it" className="flex flex-col gap-2">
          {WAYS.map((w) => (
            <button
              key={w.key} type="button" role="radio" aria-checked={way === w.key} data-way={w.key} tabIndex={way === w.key ? 0 : -1}
              className={cn('flex flex-col gap-1 rounded-[10px] border-[1.5px] px-3.5 py-3 text-left text-ptext transition-colors', way === w.key ? 'border-volt bg-psunk' : 'border-pline hover:border-pmuted')}
              onClick={() => setWay(w.key)}
              onKeyDown={(e) => walk(e, '[role="radio"]', (el) => setWay(el.dataset.way as Way))}
            >
              <span className="disp text-[15px] font-semibold">{w.h}</span>
              <span className="text-[13px] text-pmuted">{w.d}</span>
            </button>
          ))}
        </div>

        {way === 'record' && (
          <div className="flex flex-col gap-3.5">
            <div
              className={cn('flex items-center gap-3.5 rounded-xl border-[1.5px] border-dashed p-[18px] transition-colors', fileOver ? 'border-volt bg-psunk' : 'border-pline')}
              onDragOver={(e: DragEvent) => { e.preventDefault(); setFileOver(true) }} onDragLeave={() => setFileOver(false)}
              onDrop={(e: DragEvent) => { e.preventDefault(); setFileOver(false); tookFile(e.dataTransfer?.files ?? null) }}
            >
              <button
                type="button" className={cn('btn volt shrink-0 rounded-full p-0 shadow-none', recording && 'rec')} style={{ width: 52, height: 52 }}
                aria-label={recording ? 'Stop recording' : 'Start recording'} aria-pressed={recording} disabled={!canRecord || busy}
                title={canRecord ? undefined : 'Recording is not available in this browser; drop a file instead.'}
                onClick={() => (recording ? stopRecording() : void startRecording())}
              >
                <span aria-hidden="true" className={cn('block bg-ink', recording ? 'size-3.5 rounded-sm' : 'size-4 rounded-full')} />
              </button>
              <div className="flex min-w-0 flex-col">
                {recording ? (
                  <><span className="font-medium" role="status">Recording · <span className="tnum">{mmss(elapsed)}</span></span><span className="text-[13px] text-pmuted">Stop when you have a minute, or at least 10 s</span></>
                ) : file ? (
                  <><span className="truncate font-medium">{file.name}</span><button type="button" className="act self-start px-0 text-pmuted" onClick={() => setFile(null)}>Clear</button></>
                ) : (
                  <><span className="font-medium">{canRecord ? 'Record, or drop a file' : 'Drop a file'}</span><span className="text-[13px] text-pmuted">10 s at least; a minute sounds best · <button type="button" className="underline" onClick={() => fileInput.current?.click()}>choose a file</button></span></>
                )}
              </div>
              <input ref={fileInput} type="file" accept="audio/*,video/*" className="sr-only" aria-label="Choose a recording" tabIndex={-1} onChange={(e) => { tookFile(e.target.files); e.target.value = '' }} />
            </div>
            <label htmlFor={`${uid}-vname-r`} className="tag text-pmuted">Name</label>
            <input id={`${uid}-vname-r`} type="text" className={field} value={recName} onChange={(e) => setRecName(e.target.value)} maxLength={40} />
          </div>
        )}

        {way === 'describe' && (
          <div className="flex flex-col gap-2.5">
            <label htmlFor={`${uid}-vdesc`} className="tag text-pmuted">Describe the voice</label>
            <textarea id={`${uid}-vdesc`} rows={4} className={cn(field, 'h-auto resize-none rounded-[10px] p-3')} value={desc} onChange={(e) => setDesc(e.target.value)} disabled={previews !== null} placeholder="A calm British man in his thirties, low and close to the mic, a dry smile in it. For tech explainers." />
            <span className="text-[13px] text-pmuted">Voltage writes a sample line and designs three previews. You pick one; it can't hear them.</span>
            {previews && (
              <div className="flex flex-col gap-2" role="radiogroup" aria-label="Previews">
                {previews.map((p, i) => {
                  const url = voiceSampleUrl(p.sha256)
                  const on = chosen === p.generated_voice_id
                  return (
                    <div key={p.generated_voice_id} className={cn('flex items-center gap-3 rounded-[10px] border-[1.5px] p-3', on ? 'border-volt bg-psunk' : 'border-pline')}>
                      <HearButton url={url} name={`preview ${i + 1}`} playing={playing} onToggle={toggle} />
                      <Wave busy={playing === url} />
                      <span className="flex min-w-0 flex-1 flex-col"><span className="font-medium">Preview {i + 1}</span><span className="tnum text-[13px] text-pmuted">{p.duration.toFixed(1)} s</span></span>
                      <button type="button" role="radio" aria-checked={on} className={cn('btn sm', on ? 'volt' : 'ghost')} onClick={() => setChosen(p.generated_voice_id)}>{on ? '✓ Using' : 'Use this'}</button>
                    </div>
                  )
                })}
                <button type="button" className="act self-start px-0 text-pmuted" onClick={() => { setPreviews(null); setChosen(null) }}>Design again</button>
              </div>
            )}
            <label htmlFor={`${uid}-vname-d`} className="tag mt-1.5 text-pmuted">Name</label>
            <input id={`${uid}-vname-d`} type="text" className={field} value={descName} onChange={(e) => setDescName(e.target.value)} maxLength={40} placeholder="Explainer" />
          </div>
        )}

        {way === 'clone' && (
          <div className="flex flex-col gap-2.5">
            <label htmlFor={`${uid}-vspk`} className="tag text-pmuted">Speaker</label>
            {speakers.length === 0 ? (
              <span className="text-[13px] text-pmuted">No project speaker has enough speech to clone yet.</span>
            ) : (
              <select id={`${uid}-vspk`} className={cn(field, 'px-2.5')} value={speakerKey} onChange={(e) => pickSpeaker(e.target.value)}>
                {speakers.map((s) => <option key={`${s.video_id}:${s.label}`} value={`${s.video_id}:${s.label}`}>{s.name} · {s.filename.replace(/\.[^.]+$/, '')} · {Math.round(s.seconds)} s</option>)}
              </select>
            )}
            <span className="text-[13px] text-pmuted">Cloned from everything they say in the clip.</span>
            <label htmlFor={`${uid}-vname-c`} className="tag mt-1.5 text-pmuted">Name</label>
            <input id={`${uid}-vname-c`} type="text" className={field} value={cloneName} onChange={(e) => setCloneName(e.target.value)} maxLength={40} />
          </div>
        )}

        <label className="flex cursor-pointer items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 size-[18px] accent-volt" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>I have the right to use this voice. <span className="text-pmuted">Recorded with the voice. Deleting the voice withdraws it.</span></span>
        </label>

        {formError && <p className="m-0 text-sm text-warn" role="alert">{formError}</p>}
        <p className="m-0 min-h-5 text-sm text-pmuted" role="status">{note ?? ''}</p>

        <div className="mt-auto flex flex-wrap items-center gap-3">
          <button type="button" className="btn volt flex-auto" onClick={() => void submit()} disabled={!canGo}>
            <Bolt />{busy ? 'Working…' : cta.label}
          </button>
          <span className="tnum text-[13px] text-pmuted">{cta.cost}</span>
        </div>
      </aside>
    </Shell>
  )
}
