import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Loader2, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import {
  applyTemplate, deleteTemplate, importTemplate, listTemplates, preflightTemplate, saveTemplate, templatePackageUrl,
  templatePreviewUrl, TEMPLATE_LICENSES, type TemplatePreflight, type TemplateSummary,
} from '../../api/templates'
import type { Scene3DDocument } from './types.ts'
import { parseScene3DDocument } from './document.ts'
import { authorLabel, packFromApplied, readAuthor, rememberAuthor, saveInput, type TemplateForm } from './templateLibraryModel'
import type { World3DUserTemplate } from './userTemplates.ts'

const field = 'mt-1 block min-h-10 w-full rounded-lg border border-border bg-bg-primary px-3 text-text-primary'
const button = 'inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-border px-3 text-xs hover:bg-bg-hover disabled:opacity-40'

function SaveForm({ disabled, busy, fallbackTitle, onSave }: {
  disabled: boolean; busy: boolean; fallbackTitle: string; onSave: (form: TemplateForm) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [form, setForm] = useState<TemplateForm>(() => ({ title: '', description: '', tags: '', includeMedia: false, durationControl: true, ...readAuthor() }))
  const set = (patch: Partial<TemplateForm>) => setForm(current => ({ ...current, ...patch }))
  return <details className="mt-3 rounded-lg border border-border bg-bg-primary/60 p-3">
    <summary className="cursor-pointer text-xs font-medium text-text-primary">{t('userTemplates.saveTitle')}</summary>
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      <label className="text-xs text-text-secondary">{t('userTemplates.name')}
        <input value={form.title} maxLength={80} disabled={disabled} placeholder={fallbackTitle} onChange={event => set({ title: event.target.value })} className={field} />
      </label>
      <label className="text-xs text-text-secondary">{t('userTemplates.tags')}
        <input value={form.tags} maxLength={200} disabled={disabled} placeholder={t('userTemplates.tagsHint')} onChange={event => set({ tags: event.target.value })} className={field} />
      </label>
      <label className="text-xs text-text-secondary sm:col-span-2">{t('userTemplates.description')}
        <input value={form.description} maxLength={600} disabled={disabled} onChange={event => set({ description: event.target.value })} className={field} />
      </label>
      <label className="text-xs text-text-secondary">{t('userTemplates.author')}
        <input value={form.authorName} maxLength={80} disabled={disabled} onChange={event => set({ authorName: event.target.value })} className={field} />
      </label>
      <label className="text-xs text-text-secondary">{t('userTemplates.authorX')}
        <input value={form.authorX} maxLength={31} disabled={disabled} placeholder="@usuario" onChange={event => set({ authorX: event.target.value })} className={field} />
      </label>
      <label className="text-xs text-text-secondary">{t('userTemplates.license')}
        <select value={form.license} disabled={disabled} onChange={event => set({ license: event.target.value as TemplateForm['license'] })} className={field}>
          {TEMPLATE_LICENSES.map(license => <option key={license} value={license}>{t(`userTemplates.licenses.${license}`, { defaultValue: license })}</option>)}
        </select>
      </label>
      <div className="flex flex-col justify-end gap-1 text-xs text-text-secondary">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.includeMedia} disabled={disabled} onChange={event => set({ includeMedia: event.target.checked })} />{t('userTemplates.includeMedia')}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.durationControl} disabled={disabled} onChange={event => set({ durationControl: event.target.checked })} />{t('userTemplates.durationControl')}</label>
      </div>
    </div>
    <p className="mt-2 text-[11px] text-text-muted">{t(form.includeMedia ? 'userTemplates.includeMediaWarning' : 'userTemplates.slotsHint')}</p>
    <button type="button" disabled={disabled || busy} data-testid="world3d-export-template" className={`${button} mt-2`}
      onClick={() => { rememberAuthor(form); onSave({ ...form, title: form.title.trim() || fallbackTitle }) }}>{t('userTemplates.save')}</button>
  </details>
}

function ImportReview({ report, busy, onConfirm, onCancel }: { report: TemplatePreflight; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const template = report.template
  return <div role="dialog" aria-label={t('userTemplates.reviewTitle')} className="mt-3 rounded-lg border border-cyan-300/50 bg-cyan-300/5 p-3 text-xs">
    {!report.canImport || !template
      ? <p role="alert" className="text-red-300">{report.error?.message || t('userTemplates.invalid')}</p>
      : <>
        <p className="font-semibold text-text-primary">{template.title} <span className="font-normal text-text-muted">· {template.id} · v{template.templateVersion}</span></p>
        <p className="mt-1 text-text-secondary">{t('userTemplates.reviewMeta', { author: authorLabel(template.author) || '—', license: template.license, editor: template.editor })}</p>
        <p className="mt-1 text-text-secondary">{t('userTemplates.reviewContents', { slots: template.slots.length, controls: template.controls.length, media: report.media?.length ?? 0 })}</p>
        {report.issues?.map(issue => <p key={issue.message} className="mt-1 text-amber-200">{issue.message}</p>)}
        {report.exists && <p className="mt-1 text-amber-200">{t('userTemplates.reviewExists')}</p>}
      </>}
    <div className="mt-2 flex gap-2">
      {report.canImport && <button type="button" className={button} disabled={busy} onClick={onConfirm}>{t(report.exists ? 'userTemplates.replace' : 'userTemplates.confirmImport')}</button>}
      <button type="button" className={button} onClick={onCancel}>{t('userTemplates.cancel')}</button>
    </div>
  </div>
}

function TemplateCard({ item, selected, disabled, onPick, onDelete }: {
  item: TemplateSummary; selected: boolean; disabled: boolean; onPick: () => void; onDelete: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const preview = templatePreviewUrl(item)
  return <article className={`overflow-hidden rounded-lg border ${selected ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary'}`}>
    <button type="button" disabled={disabled} data-testid={`world3d-user-template-${item.id}`} aria-label={item.title} aria-pressed={selected}
      onClick={onPick} className="block w-full text-left disabled:opacity-40">
      {preview ? <img src={preview} alt="" className="aspect-video w-full object-cover" loading="lazy" /> : <div className="aspect-video w-full bg-bg-tertiary" />}
      <div className="p-3">
        <span className="text-sm font-semibold text-text-primary">{item.title}</span>
        <span className="mt-1 block text-xs leading-5 text-text-secondary">{item.description || t('userTemplates.noDescription')}</span>
        <span className="mt-1 block text-[11px] text-text-muted">
          {[authorLabel(item.author), item.license, t(`userTemplates.source.${item.source}`), t('userTemplates.slotCount', { count: item.slots.length })].filter(Boolean).join(' · ')}
        </span>
        {item.tags.length > 0 && <span className="mt-1 block text-[11px] text-cyan-200">{item.tags.map(tag => `#${tag}`).join(' ')}</span>}
      </div>
    </button>
    <div className="flex gap-3 border-t border-border px-3 py-2 text-xs">
      <a href={templatePackageUrl(item.id)} download className="inline-flex items-center gap-1 text-text-muted hover:text-text-primary"><Download size={12} /> {t('userTemplates.download')}</a>
      <button type="button" disabled={disabled} className="inline-flex items-center gap-1 text-text-muted hover:text-red-300" aria-label={`${t('userTemplates.remove')} ${item.title}`}
        onClick={onDelete}><Trash2 size={12} /> {t('userTemplates.remove')}</button>
    </div>
  </article>
}

/** "My scenarios": the server template library (Video 3D) — save, use, download, import. */
export function Scene3DUserTemplates({ document, workspace = 'default', preview, disabled, selectedId, onApply }: {
  document: Scene3DDocument
  workspace?: string
  preview?: () => string | undefined
  disabled: boolean
  selectedId?: string
  onApply: (pack: World3DUserTemplate) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const input = useRef<HTMLInputElement>(null)
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [review, setReview] = useState<{ file: File; report: TemplatePreflight } | null>(null)
  const fallbackTitle = t(`template.${document.templateId}.title`)

  const reload = useCallback(async () => {
    try { setTemplates(await listTemplates('video3d')) } catch (failure) { setError((failure as Error).message) }
  }, [])
  useEffect(() => { void reload() }, [reload])

  const run = async (action: () => Promise<string | void>) => {
    setBusy(true); setError(''); setNote('')
    try { const message = await action(); if (message) setNote(message) } catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }
  const save = (form: TemplateForm) => void run(async () => {
    await saveTemplate(saveInput(document, form, workspace, preview?.())); await reload(); return t('userTemplates.saved')
  })
  const pick = (item: TemplateSummary) => void run(async () => {
    const applied = await applyTemplate<Scene3DDocument>(item.id, workspace)
    const parsed = parseScene3DDocument(applied.document)
    if (!parsed) throw new Error(t('userTemplates.invalid'))
    onApply(packFromApplied(item, parsed))
    return applied.missingSlots.length ? t('userTemplates.missingSlots', { slots: applied.missingSlots.join(', ') }) : ''
  })
  const remove = (item: TemplateSummary) => {
    if (!window.confirm(t('userTemplates.confirmRemove', { title: item.title }))) return
    void run(async () => { await deleteTemplate(item.id); await reload(); return t('userTemplates.removed') })
  }
  const choose = (file: File) => void run(async () => { setReview({ file, report: await preflightTemplate(file) }) })
  const confirmImport = () => review && void run(async () => {
    await importTemplate(review.file, Boolean(review.report.exists)); setReview(null); await reload(); return t('userTemplates.imported')
  })

  return <section className="border-t border-border px-1 pt-3" aria-label={t('userTemplates.title')} data-testid="world3d-user-templates">
    <div className="flex flex-wrap items-center gap-2">
      <h3 className="mr-auto text-sm font-semibold text-text-primary">{t('userTemplates.title')} <span className="ml-1 text-text-muted">{templates?.length ?? ''}</span></h3>
      {busy && <Loader2 size={14} className="animate-spin text-text-muted" />}
      <button type="button" disabled={disabled || busy} data-testid="world3d-import-template" onClick={() => input.current?.click()} className={button}>
        <Upload size={13} /> {t('userTemplates.import')}
      </button>
      <input ref={input} type="file" accept=".hptemplate,.json,application/zip,application/json" aria-label={t('userTemplates.chooseFile')} disabled={disabled} className="hidden"
        onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) choose(file) }} />
    </div>
    <p className="mt-1 text-xs leading-5 text-text-secondary">{t('userTemplates.help')}</p>
    <SaveForm disabled={disabled} busy={busy} fallbackTitle={fallbackTitle} onSave={save} />
    {review && <ImportReview report={review.report} busy={busy} onConfirm={confirmImport} onCancel={() => setReview(null)} />}
    {note && <p role="status" className="mt-2 text-xs text-text-secondary">{note}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-red-300">{error}</p>}
    <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2">
      {(templates ?? []).map(item => <TemplateCard key={item.id} item={item} selected={selectedId === item.id} disabled={disabled || busy}
        onPick={() => pick(item)} onDelete={() => remove(item)} />)}
    </div>
    {templates?.length === 0 && <p role="status" className="p-3 text-xs text-text-secondary">{t('userTemplates.empty')}</p>}
  </section>
}
