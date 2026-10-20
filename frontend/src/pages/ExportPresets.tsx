import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { ExportPreset, ExportPresetChange, ExportPresetPage } from '../types'
import { addExportPreset, changeExportPreset, listExportPresets, removeExportPreset } from '../api'
import { said } from './fmt'
import { presetFacts } from '../lib/exports'

const inputClass = 'h-8 min-w-0 rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

type Draft = Required<ExportPresetChange>

function PresetForm({ page, start, busy, onSave, onCancel }: { page: ExportPresetPage; start: Draft; busy: boolean; onSave: (d: Draft) => void; onCancel: () => void }) {
  const [d, setD] = useState<Draft>(start)
  const set = (change: Partial<Draft>) => setD((x) => ({ ...x, ...change }))
  const submit = (e: FormEvent) => { e.preventDefault(); if (d.name.trim() && d.pattern.trim()) onSave({ ...d, name: d.name.trim(), pattern: d.pattern.trim() }) }
  return (
    <form className="flex flex-col gap-2.5 rounded-lg bg-sunk p-3" onSubmit={submit} aria-label="Preset" data-testid="preset-form">
      <label className="flex flex-col gap-1 text-[13px]"><span className="text-muted-foreground">Name</span>
        <input className={inputClass} value={d.name} onChange={(e) => set({ name: e.target.value })} maxLength={60} required autoFocus />
      </label>
      <div className="flex flex-col gap-1 text-[13px]"><span className="text-muted-foreground" id="preset-platform">Frame</span>
        <div className="segs self-start" role="group" aria-labelledby="preset-platform">
          {page.platforms.map((p) => <button key={p.id} type="button" className="seg" aria-pressed={d.platform === p.id} onClick={() => set({ platform: p.id })}>{p.label}</button>)}
        </div>
      </div>
      <div className="flex flex-col gap-1 text-[13px]"><span className="text-muted-foreground" id="preset-codec">Codec</span>
        <div className="segs self-start" role="group" aria-labelledby="preset-codec">
          {page.codecs.map((c) => <button key={c.id} type="button" className="seg" aria-pressed={d.codec === c.id} disabled={!c.available} title={c.available ? undefined : 'This server cannot write it'} onClick={() => set({ codec: c.id })}>{c.label}</button>)}
        </div>
      </div>
      <div className="flex flex-col gap-1 text-[13px]"><span className="text-muted-foreground" id="preset-loudness">Loudness</span>
        <div className="segs flex-wrap self-start" role="group" aria-labelledby="preset-loudness">
          {page.loudness.map((l) => <button key={l.lufs} type="button" className="seg" aria-pressed={d.loudness === l.lufs} onClick={() => set({ loudness: l.lufs })}>{l.label}</button>)}
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="size-4 accent-volt" checked={d.captions} disabled={!page.captions && !d.captions} onChange={(e) => set({ captions: e.target.checked })} />
        Burn captions into the picture{!page.captions && <span className="text-[13px] text-muted-foreground"> (this server cannot draw them)</span>}
      </label>
      <label className="flex flex-col gap-1 text-[13px]"><span className="text-muted-foreground">File name</span>
        <input className={`${inputClass} tnum`} value={d.pattern} onChange={(e) => set({ pattern: e.target.value })} maxLength={120} required aria-describedby="preset-tokens" />
      </label>
      <span id="preset-tokens" className="-mt-1.5 text-[13px] text-faint">Use {page.tokens.map((t) => `{${t}}`).join(' ')}. Language is en until videos have one.</span>
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className="act" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn sm" disabled={busy || !d.name.trim() || !d.pattern.trim()}>{busy ? 'Saving…' : 'Save preset'}</button>
      </div>
    </form>
  )
}

/** B3 (projects.batch): the project's export presets: a frame, a codec, a
 *  loudness target, captions on or off and a file name pattern each. The
 *  first visit gets YouTube 16:9, Reels 9:16 and Feed 1:1. `onChanged` tells
 *  the export panel the list moved. */
export function ExportPresets({ projectId, onChanged }: { projectId: string; onChanged?: (presets: ExportPreset[]) => void }) {
  const [page, setPage] = useState<ExportPresetPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState<number | 'new' | null>(null)

  const load = () => {
    setError(null)
    listExportPresets(projectId).then((raw) => { const p = { ...raw, presets: raw.presets ?? [], platforms: raw.platforms ?? [], codecs: raw.codecs ?? [], loudness: raw.loudness ?? [], tokens: raw.tokens ?? [] }; setPage(p); onChanged?.(p.presets) }).catch((e) => setError(said(e, 'Could not read the presets.')))
  }
  useEffect(load, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const put = (presets: ExportPreset[]) => { setPage((p) => (p ? { ...p, presets } : p)); onChanged?.(presets) }
  const act = async (key: string, fn: () => Promise<void>, fallback: string) => {
    setBusy(key)
    setNote(null)
    try { await fn(); setEditing(null) } catch (e) { setNote(said(e, fallback)) } finally { setBusy(null) }
  }
  const save = (d: Draft) => {
    if (!page) return
    if (editing === 'new') void act('new', async () => put([...page.presets, await addExportPreset(projectId, d)]), 'Could not add the preset.')
    else if (editing !== null) {
      const id = editing
      void act(`p-${id}`, async () => { const next = await changeExportPreset(projectId, id, d); put(page.presets.map((p) => (p.preset_id === id ? next : p))) }, 'Could not change the preset.')
    }
  }
  const remove = (p: ExportPreset) => {
    if (!page) return
    void act(`rm-${p.preset_id}`, async () => { await removeExportPreset(projectId, p.preset_id); put(page.presets.filter((x) => x.preset_id !== p.preset_id)) }, 'Could not remove the preset.')
  }
  const blank: Draft = { name: '', platform: 'youtube', codec: 'h264', loudness: -14, captions: false, pattern: page?.default_pattern ?? '{project}_{video}_{lang}_{preset}_v{version}' }

  return (
    <section aria-label="Export presets" className="rise flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="export-presets">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-xl font-bold">Presets</h2>
        <span className="tag text-faint">How each file is made</span>
        <span className="flex-1" />
        {page && editing === null && <button type="button" className="btn sm" onClick={() => setEditing('new')}>+ Add preset</button>}
      </div>
      {error && (
        <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
          <span className="flex-1">{error}</span><button type="button" className="btn sm" onClick={load}>Try again</button>
        </div>
      )}
      {!error && !page && <p className="m-0 text-sm text-muted-foreground" role="status">Reading the presets…</p>}
      {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}
      {page && page.presets.length === 0 && editing === null && <p className="m-0 text-[13px] text-muted-foreground">No presets. Add one to export this project's videos.</p>}
      {page && page.presets.map((p) => (editing === p.preset_id ? (
        <PresetForm key={p.preset_id} page={page} busy={busy === `p-${p.preset_id}`} onCancel={() => setEditing(null)} onSave={save}
          start={{ name: p.name, platform: p.platform, codec: p.codec, loudness: p.loudness, captions: p.captions, pattern: p.pattern }} />
      ) : (
        <div key={p.preset_id} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 border-t border-line py-2 first-of-type:border-t-0" data-testid="preset">
          <span className="min-w-0 flex-1 font-semibold">{p.name}</span>
          <button type="button" className="act" onClick={() => setEditing(p.preset_id)} disabled={busy !== null || editing !== null} aria-label={`Edit ${p.name}`}>Edit</button>
          <button type="button" className="act" onClick={() => remove(p)} disabled={busy !== null || editing !== null} aria-label={`Remove ${p.name}`}>{busy === `rm-${p.preset_id}` ? 'Removing…' : 'Remove'}</button>
          <span className="w-full text-[13px] text-muted-foreground">{presetFacts(p, page)}</span>
          <span className="tnum w-full truncate text-xs text-faint" title={p.pattern}>{p.pattern}.mp4</span>
        </div>
      )))}
      {page && editing === 'new' && <PresetForm page={page} start={blank} busy={busy === 'new'} onCancel={() => setEditing(null)} onSave={save} />}
    </section>
  )
}
