import { useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { Scene3DDocument } from './types.ts'
import {
  createUserTemplate,
  downloadUserTemplate,
  parseUserTemplate,
  readStoredUserTemplates,
  removeUserTemplate,
  saveUserTemplate,
  templateFileTooLarge,
  type World3DUserTemplate,
} from './userTemplates.ts'

export function Scene3DUserTemplates({ document, disabled, selectedId, onApply }: {
  document: Scene3DDocument
  disabled: boolean
  selectedId?: string
  onApply: (pack: World3DUserTemplate) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const input = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [includeAssets, setIncludeAssets] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [templates, setTemplates] = useState(readStoredUserTemplates)
  const fallbackTitle = t(`template.${document.templateId}.title`)

  const exportScenario = () => {
    const pack = createUserTemplate({ document, title: title.trim() || fallbackTitle, description, includeAssets })
    if (!pack) { setError(t('userTemplates.needTitle')); setNote(''); return }
    try {
      setTemplates(saveUserTemplate(pack))
      downloadUserTemplate(pack)
      setNote(t('userTemplates.exported')); setError('')
    } catch { setError(t('userTemplates.saveFailed')); setNote('') }
  }

  const importFile = async (file: File) => {
    if (templateFileTooLarge(file.size)) { setError(t('userTemplates.tooLarge')); setNote(''); return }
    try {
      const pack = parseUserTemplate(JSON.parse(await file.text()))
      if (!pack) throw new Error('template')
      setTemplates(saveUserTemplate(pack))
      setNote(t('userTemplates.imported')); setError('')
    } catch { setError(t('userTemplates.invalid')); setNote('') }
  }

  return <section className="border-t border-border px-1 pt-3" aria-label={t('userTemplates.title')} data-testid="world3d-user-templates">
    <h3 className="text-sm font-semibold text-text-primary">{t('userTemplates.title')} <span className="ml-1 text-text-muted">{templates.length}</span></h3>
    <p className="mt-1 text-xs leading-5 text-text-secondary">{t('userTemplates.help')}</p>
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <label className="text-xs text-text-secondary">{t('userTemplates.name')}
        <input value={title} maxLength={80} disabled={disabled} placeholder={fallbackTitle} aria-label={t('userTemplates.name')}
          onChange={event => setTitle(event.target.value)}
          className="mt-1 block min-h-10 min-w-[12rem] rounded-lg border border-border bg-bg-primary px-3 text-text-primary" />
      </label>
      <label className="text-xs text-text-secondary">{t('userTemplates.description')}
        <input value={description} maxLength={240} disabled={disabled} aria-label={t('userTemplates.description')}
          onChange={event => setDescription(event.target.value)}
          className="mt-1 block min-h-10 min-w-[16rem] flex-1 rounded-lg border border-border bg-bg-primary px-3 text-text-primary" />
      </label>
      <label className="flex min-h-10 items-center gap-2 text-xs text-text-secondary">
        <input type="checkbox" checked={includeAssets} disabled={disabled} onChange={event => setIncludeAssets(event.target.checked)} />
        {t('userTemplates.includeAssets')}
      </label>
      <button type="button" disabled={disabled} data-testid="world3d-export-template" onClick={exportScenario}
        className="min-h-10 rounded-lg border border-border px-3 text-xs">{t('userTemplates.export')}</button>
      <button type="button" disabled={disabled} data-testid="world3d-import-template" onClick={() => input.current?.click()}
        className="min-h-10 rounded-lg border border-border px-3 text-xs">{t('userTemplates.import')}</button>
      <input ref={input} type="file" accept=".json,application/json" aria-label={t('userTemplates.chooseFile')} disabled={disabled} className="hidden"
        onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importFile(file) }} />
    </div>
    {note && <p role="status" className="mt-2 text-xs text-text-secondary">{note}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-red-300">{error}</p>}
    <div className="mt-3 grid max-h-56 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
      {templates.map(pack => <article key={pack.id} className={`rounded-lg border p-3 ${selectedId === pack.id ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary'}`}>
        <button type="button" disabled={disabled} data-testid={`world3d-user-template-${pack.id}`} aria-label={pack.title} aria-pressed={selectedId === pack.id}
          onClick={() => onApply(pack)} className="block w-full text-left disabled:opacity-40">
          <span className="text-sm font-semibold text-text-primary">{pack.title}</span>
          <span className="mt-1 block text-xs leading-5 text-text-secondary">{pack.description || t('userTemplates.noDescription')}</span>
        </button>
        <button type="button" disabled={disabled} className="mt-2 text-xs underline text-text-muted"
          aria-label={`${t('userTemplates.remove')} ${pack.title}`}
          onClick={() => { setTemplates(removeUserTemplate(pack.id)); setNote(t('userTemplates.removed')); setError('') }}>
          {t('userTemplates.remove')}
        </button>
      </article>)}
    </div>
    {templates.length === 0 && <p role="status" className="p-3 text-xs text-text-secondary">{t('userTemplates.empty')}</p>}
  </section>
}
