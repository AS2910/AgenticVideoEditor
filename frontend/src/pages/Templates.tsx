import { useCallback, useEffect, useRef, useState } from 'react'
import { track } from '../lib/analytics'
import type { ProjectTemplate } from '../types'
import type { Me } from '../api'
import { ApiError, createFolderFrom, deleteTemplate, listTemplates, renameTemplate, saveTemplate } from '../api'
import { go, hrefFor } from '../lib/route'
import { Tip } from '../guides/Tip'
import { Shell } from './Shell'
import { said } from './fmt'
import { formatDate } from '../lib/dates'
import { VoiceQuestion } from '../components/VoiceQuestion'
import { belongsTo, templateFacts } from '../lib/templates'
import type { VoiceChoice } from '../components/VoiceQuestion'

/** D1: Save as template, from the project page's •••. The name, what goes in
 *  (and that videos stay), and, when the project has voices of its own, the
 *  move's question: copy into the template, or keep in my voices. */
export function SaveTemplateDialog({ projectId, projectName, onClose, onSaved }: {
  projectId: string; projectName: string; onClose: () => void; onSaved?: (t: ProjectTemplate) => void
}) {
  const [name, setName] = useState(`${projectName} template`)
  useEffect(() => { track('template.dialog_opened') }, [])
  const [voices, setVoices] = useState<{ voice_id: string; name: string }[] | null>(null)
  const [voice, setVoice] = useState<VoiceChoice>('copy')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<ProjectTemplate | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { input.current?.select() }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key === 'Tab' && box.current) {
        const items = Array.from(box.current.querySelectorAll<HTMLElement>('button:not([disabled]), input, [href]'))
        if (items.length === 0) return
        const a = items[0], z = items[items.length - 1]
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus() }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus() }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const save = async () => {
    if (!name.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const t = await saveTemplate(projectId, name.trim(), voices ? voice : undefined)
      setSaved(t)
      onSaved?.(t)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const body = e.body as { voices?: { voice_id: string; name: string }[] } | null
        setVoices(Array.isArray(body?.voices) && body.voices.length ? body.voices : [{ voice_id: '', name: 'A project voice' }])
      } else {
        setError(said(e, 'Could not save the template.'))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/60 p-4" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={box} role="dialog" aria-modal="true" aria-label="Save as template" className="rise flex max-h-[calc(100dvh-32px)] w-full max-w-[560px] flex-col gap-4 overflow-y-auto rounded-xl border-[1.5px] border-ink bg-card p-6 shadow-volt-lg sm:px-7" data-testid="save-template">
        <div className="flex flex-col gap-0.5">
          <span className="tag text-faint">Save as template</span>
          <span className="disp text-[26px] font-bold">{projectName}</span>
          <span className="text-muted-foreground">A template keeps the brief, the words and rules, the export presets, the defaults for new videos and the ceiling. Videos stay here. Voices are linked, not copied.</span>
        </div>
        {saved ? (
          <>
            <p className="m-0 rounded-[10px] border-[1.5px] border-foreground bg-sunk p-3.5" role="status" data-testid="template-saved">
              <span className="stamp mr-2">Saved</span>{saved.name}. {templateFacts(saved)}. Start a project from it with New project on Home.
            </p>
            <div className="flex flex-wrap justify-end gap-2.5">
              <a className="btn no-underline" href={hrefFor({ page: 'templates' })}>See templates</a>
              <button type="button" className="btn volt" onClick={onClose}>Done</button>
            </div>
          </>
        ) : (
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void save() }}>
            <label className="flex flex-col gap-1.5 text-sm font-semibold" htmlFor="template-name">Template name
              <input ref={input} id="template-name" className="h-10 rounded-md border-[1.5px] border-line2 bg-background px-2.5 text-base font-normal outline-none focus-visible:border-ink focus-visible:ring-[3px] focus-visible:ring-volt" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </label>
            {voices && (
              <VoiceQuestion lead={`${belongsTo(voices, projectName)}.`}
                copyLabel="Copy the voice into the template" value={voice} onChange={setVoice}
                note="Either way the voice is not made again. This decides where it lives: only in projects made from the template, or also in your voices." />
            )}
            {error && <div className="text-sm text-destructive" role="alert">{error}</div>}
            <div className="flex flex-wrap justify-end gap-2.5">
              <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
              <button type="submit" className="btn volt" disabled={busy || !name.trim()} aria-busy={busy || undefined}>{busy ? 'Saving…' : 'Save template'}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

/** One template in the list: its name and facts; a starter is read-only, your
 *  own can be renamed and deleted (asked first). Either starts a project. */
function TemplateRow({ t, busy, error, onRename, onDelete, onStart }: {
  t: ProjectTemplate; busy: boolean; error: string | null
  onRename: (name: string) => Promise<boolean>; onDelete: () => Promise<boolean>; onStart: (name: string) => Promise<boolean>
}) {
  const [mode, setMode] = useState<'rename' | 'delete' | 'start' | null>(null)
  const [text, setText] = useState('')
  const open = (m: 'rename' | 'start') => { setMode(m); setText(m === 'rename' ? t.name : '') }
  const submit = async () => {
    if (!text.trim()) return
    const ok = mode === 'rename' ? await onRename(text.trim()) : await onStart(text.trim())
    if (ok) setMode(null)
  }
  return (
    <li className="rise flex flex-col gap-2 border-b border-line py-3.5 last:border-b-0" data-testid={`template-${t.template_id}`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex min-w-0 flex-[1_1_280px] flex-col gap-0.5">
          <span className="flex items-center gap-2"><span className="truncate font-semibold" title={t.name}>{t.name}</span>{t.starter && <span className="stamp in whitespace-nowrap">Starter</span>}</span>
          {t.description && <span className="text-[13px]">{t.description}</span>}
          <span className="text-[13px] text-muted-foreground">{templateFacts(t)}{!t.starter && t.created_at ? ` · saved ${formatDate(t.created_at)}` : ''}</span>
        </span>
        {!t.starter && <button type="button" className="act" onClick={() => open('rename')} disabled={busy} aria-label={`Rename ${t.name}`}>Rename</button>}
        {!t.starter && <button type="button" className="act" onClick={() => setMode('delete')} disabled={busy} aria-label={`Delete ${t.name}`}>Delete</button>}
        <button type="button" className="btn sm" onClick={() => open('start')} disabled={busy} aria-label={`New project from ${t.name}`}>New project from this</button>
      </div>
      {(mode === 'rename' || mode === 'start') && (
        <form className="flex flex-wrap items-center gap-2 rounded-lg bg-sunk p-2.5" onSubmit={(e) => { e.preventDefault(); void submit() }} onKeyDown={(e) => { if (e.key === 'Escape') setMode(null) }}>
          <label className="sr-only" htmlFor={`tpl-${t.template_id}`}>{mode === 'rename' ? 'New name' : 'Project name'}</label>
          <input id={`tpl-${t.template_id}`} autoFocus className="h-9 min-w-0 flex-[1_1_200px] rounded-md border-[1.5px] border-line2 bg-background px-2.5 outline-none focus-visible:border-ink focus-visible:ring-[3px] focus-visible:ring-volt"
            placeholder={mode === 'rename' ? 'Template name' : 'Project name'} value={text} maxLength={80} onChange={(e) => setText(e.target.value)} />
          <button type="button" className="act" onClick={() => setMode(null)}>Cancel</button>
          <button type="submit" className="btn volt sm" disabled={busy || !text.trim()} aria-busy={busy || undefined}>{busy ? 'Working…' : mode === 'rename' ? 'Save name' : 'Create project'}</button>
        </form>
      )}
      {error && <p className="m-0 text-[13px] text-destructive" role="alert">{error}</p>}
      {mode === 'delete' && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border-[1.5px] border-destructive p-2.5" role="group" aria-label={`Delete ${t.name}?`}>
          <span className="flex-1 text-sm">Delete <strong>{t.name}</strong>? Projects made from it keep everything they have.</span>
          <button type="button" className="btn sm" onClick={() => setMode(null)} disabled={busy}>Keep it</button>
          <button type="button" className="btn sm border-destructive text-destructive" onClick={() => void onDelete().then((ok) => { if (ok) setMode(null) })} disabled={busy}>Delete template</button>
        </div>
      )}
    </li>
  )
}

/** D1: the workspace's templates: the three starters, then your own (rename,
 *  delete). Any of them starts a new project. */
export function TemplatesPage({ me, onMade }: { me: Me | null; onMade?: () => void }) {
  const [items, setItems] = useState<ProjectTemplate[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; text: string } | null>(null)

  const load = useCallback(() => {
    let live = true
    setError(null)
    setItems(null)
    listTemplates().then((t) => { if (live) setItems(t) }).catch((e) => { if (live) setError(said(e, 'The templates could not be read.')) })
    return () => { live = false }
  }, [])
  useEffect(() => { track('templates.opened') }, [])
  useEffect(() => load(), [load])

  const act = async (t: ProjectTemplate, run: () => Promise<void>, fallback: string) => {
    setBusy(t.template_id)
    setRowError(null)
    try { await run(); return true } catch (e) { setRowError({ id: t.template_id, text: said(e, fallback) }); return false } finally { setBusy(null) }
  }
  const starters = (items ?? []).filter((t) => t.starter)
  const own = (items ?? []).filter((t) => !t.starter)
  const row = (t: ProjectTemplate) => (
    <TemplateRow key={t.template_id} t={t} busy={busy === t.template_id} error={rowError?.id === t.template_id ? rowError.text : null}
        onRename={(name) => act(t, async () => { const r = await renameTemplate(t.template_id, name); setItems((all) => (all ?? []).map((x) => (x.template_id === t.template_id ? r : x))) }, 'Could not rename it.')}
        onDelete={() => act(t, async () => { await deleteTemplate(t.template_id); setItems((all) => (all ?? []).filter((x) => x.template_id !== t.template_id)) }, 'Could not delete it.')}
        onStart={(name) => act(t, async () => { const made = await createFolderFrom(name, t.template_id); onMade?.(); go({ page: 'folder', projectId: made.project_id }) }, 'Could not make the project.')} />
  )

  return (
    <Shell active="projects" me={me} mainClassName="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-4 pt-10 pb-20 sm:px-6 sm:pt-12">
      <div className="flex flex-col gap-2">
        <a href={hrefFor({ page: 'projects' })} className="tag text-faint no-underline">← Home / Projects</a>
        <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Templates</h1>
        <p className="m-0 max-w-[640px] text-muted-foreground">A template starts a project with a brief, words and rules, export presets, defaults and a ceiling already set. Save your own from any project with ••• then Save as template.</p>
      </div>
      <section className="flex flex-col gap-2 rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="tpl-h" data-testid="template-list" data-tour="template-list">
        <h2 id="tpl-h" className="sr-only">Templates</h2>
        {error ? (
          <div className="flex flex-wrap items-center gap-3" role="alert">
            <span className="flex-1 text-sm text-destructive">{error}</span>
            <button type="button" className="btn sm" onClick={() => load()}>Try again</button>
          </div>
        ) : items === null ? (
          <p className="m-0 min-h-[60px] text-[13px] text-muted-foreground" role="status" aria-busy="true">Reading the templates…</p>
        ) : (
          <>
            <span className="tag text-faint">Your templates · {own.length}</span>
            {own.length === 0
              ? <p className="m-0 border-b border-line pb-3.5 text-muted-foreground" data-testid="templates-empty">No templates of your own yet. On a project page, choose ••• then Save as template.</p>
              : <ul className="m-0 flex list-none flex-col p-0">{own.map(row)}</ul>}
            <span className="tag mt-3 text-faint">Starters · {starters.length}</span>
            <ul className="m-0 flex list-none flex-col p-0">{starters.map(row)}</ul>
          </>
        )}
      </section>
      {items && <Tip id="first-template" />}
    </Shell>
  )
}
