import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { APPROVED_REFERENCE_JSON } from './approvedReferences'

const REFERENCE_BASE = 'https://github.com/IAnMove/hocuspocus/releases/download/procedural-style-reference-v1'

export function TemplateReferencePanel({ templateId, disabled, onOpen }: {
  templateId: string; disabled: boolean; onOpen: (file: File) => void
}) {
  const { t } = useUiTranslation('scene3d')
  const [show, setShow] = useState(false)
  const [failed, setFailed] = useState(false)
  const referenceToggle = show ? t('templateReference.hide') : t('templateReference.show')
  if (!Object.hasOwn(APPROVED_REFERENCE_JSON, templateId)) return <p role="status" className="rounded border border-amber-300/30 p-3 text-xs text-amber-100">{t('templateReference.pendingReview')}</p>
  return <div className="rounded border border-border p-3 text-xs">
    <button type="button" onClick={() => setShow(value => !value)} className="rounded border border-cyan-400/40 px-3 py-1.5">{referenceToggle}</button>
    {show && !failed && <video aria-label={t('templateReference.videoAria')} controls playsInline preload="metadata" src={`${REFERENCE_BASE}/${templateId}.mp4`} onError={() => setFailed(true)} className="mt-2 max-h-64 w-full rounded bg-black" />}
    {failed && <p role="status" className="mt-2">{t('templateReference.unavailable')}</p>}
    <p className="mt-2 text-text-muted">{t('templateReference.coralOriginal')}</p>
    <a href={`${REFERENCE_BASE}/${templateId}.json`} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-cyan-200 underline">{t('templateReference.download')}</a>
    <p className="mt-1 text-text-muted">{t('templateReference.openInstructions')}</p>
    <label className="mt-2 block">{t('templateReference.openVerified')}<input aria-label={t('templateReference.openVerified')} type="file" accept="application/json,.json" disabled={disabled} onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) onOpen(file) }} className="mt-1 block w-full disabled:opacity-40" /></label>
  </div>
}
