import { lazy, Suspense, useState } from 'react'
import { LayoutGrid } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Scene3DTemplateThumb } from './Scene3DTemplateThumb'
import type { ShotLibraryProps } from './Scene3DShotLibrary'
import { isBuiltinScene3DTemplate } from './templateCatalog'
import { userTemplateTitle } from './templateLibraryModel'

const Scene3DShotLibraryDialog = lazy(() => import('./Scene3DShotLibrary').then(module => ({ default: module.Scene3DShotLibraryDialog })))

type LibraryProps = Omit<ShotLibraryProps, 'onClose'>

function useLibraryDialog(props: LibraryProps) {
  const [open, setOpen] = useState(false)
  const dialog = open && <Suspense fallback={<div className="fixed inset-0 z-[130] bg-black/70" />}>
    <Scene3DShotLibraryDialog {...props} onClose={() => setOpen(false)} />
  </Suspense>
  return { show: () => setOpen(true), dialog }
}

/** «Plantillas» in the desk's top bar: the shot templates one click away. */
export function Scene3DTemplatesButton(props: LibraryProps) {
  const { t } = useUiTranslation('scene3dEditor')
  const library = useLibraryDialog(props)
  return <>
    <button type="button" onClick={library.show} data-testid="world3d-templates" title={t('desk.templatesHint')}
      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-cyan-400/50 bg-cyan-400/10 px-2.5 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/20">
      <LayoutGrid size={14} aria-hidden="true" />{t('desk.templates')}
    </button>
    {library.dialog}
  </>
}

/** The editor's compact view of the shot library: the current template and a
 *  button that opens the full library in its own dialog. */
export function Scene3DShotLibraryCard(props: LibraryProps) {
  const { t } = useUiTranslation('scene3dEditor')
  const library = useLibraryDialog(props)
  const templateId = props.document.templateId
  const builtin = isBuiltinScene3DTemplate(templateId)
  const userTitle = userTemplateTitle(props.userTemplateId) ?? userTemplateTitle(templateId)
  // A scene an agent built from a workspace template carries that template's id, which has no built-in card.
  const title = userTitle ?? (builtin ? t(`template.${templateId}.title`)
    : templateId.startsWith('stage-') ? t('stages.shotTitle', { id: templateId.slice('stage-'.length) }) : t('workspaceTemplates.shotTitle', { id: templateId }))
  return <section className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-2 rounded-xl border border-border bg-bg-secondary p-2" aria-label={t('templates')} data-testid="world3d-shot-card">
    <button type="button" onClick={library.show} className="w-full rounded-md" aria-label={t('shotLibrary.change')} title={t('desk.templatesHint')}>
      {builtin ? <Scene3DTemplateThumb id={templateId} fill /> : <div className="aspect-video w-full rounded-md bg-[#10131c]" />}
    </button>
    <div className="min-w-0">
      <p className="text-[11px] text-text-muted">{t('templates')}</p>
      <p className="line-clamp-2 text-xs font-semibold text-text-primary" title={title}>{title}</p>
    </div>
    <button type="button" onClick={library.show} data-testid="world3d-open-library" title={t('desk.templatesHint')}
      className="col-span-2 h-8 rounded-lg border border-cyan-300/60 px-2 text-xs font-medium text-cyan-100 hover:bg-cyan-300/10">{t('shotLibrary.change')}</button>
    {library.dialog}
  </section>
}
