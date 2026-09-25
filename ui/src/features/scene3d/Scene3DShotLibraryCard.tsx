import { lazy, Suspense, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { Scene3DTemplateThumb } from './Scene3DTemplateThumb'
import type { ShotLibraryProps } from './Scene3DShotLibrary'
import { readStoredUserTemplates } from './userTemplates.ts'

const Scene3DShotLibraryDialog = lazy(() => import('./Scene3DShotLibrary').then(module => ({ default: module.Scene3DShotLibraryDialog })))

/** The editor's compact view of the shot library: the current shot and a
 *  button that opens the full library in its own dialog. */
export function Scene3DShotLibraryCard(props: Omit<ShotLibraryProps, 'onClose'>) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false)
  const userTitle = props.userTemplateId ? readStoredUserTemplates().find(pack => pack.id === props.userTemplateId)?.title : undefined
  const title = userTitle ?? t(`template.${props.document.templateId}.title`)
  return <section className="flex items-center gap-3 rounded-xl border border-border bg-bg-secondary p-2" aria-label={t('templates')} data-testid="world3d-shot-card">
    <div className="w-28 shrink-0"><Scene3DTemplateThumb id={props.document.templateId} fill /></div>
    <div className="min-w-0 flex-1">
      <p className="text-xs text-text-muted">{t('templates')}</p>
      <p className="truncate text-sm font-semibold text-text-primary">{title}</p>
    </div>
    <button type="button" onClick={() => setOpen(true)} data-testid="world3d-open-library"
      className="min-h-10 shrink-0 rounded-lg border border-cyan-300/60 px-3 text-sm font-medium text-cyan-100 hover:bg-cyan-300/10">{t('shotLibrary.change')}</button>
    {open && <Suspense fallback={<div className="fixed inset-0 z-[130] bg-black/70" />}>
      <Scene3DShotLibraryDialog {...props} onClose={() => setOpen(false)} />
    </Suspense>}
  </section>
}
