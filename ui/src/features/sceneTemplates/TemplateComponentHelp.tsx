import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { templateComponentPrompt } from './componentContract'
import { getCandidateSceneTemplate } from './catalog'

export function TemplateComponentHelp({ templateId }: { templateId: string }) {
  const { t } = useUiTranslation('scene3d')
  const [message, setMessage] = useState('')
  const contract = templateComponentPrompt(templateId)
  const motion = getCandidateSceneTemplate(templateId).motionIntensity
  const motionWord = motion === 'high' ? t('templateComponent.motionStrong') : t('templateComponent.motionModerate')
  const copy = async () => {
    try { await navigator.clipboard.writeText(contract); setMessage(t('templateComponent.copied')) }
    catch { setMessage(t('templateComponent.copyFailed')) }
  }
  return <div className="rounded border border-border p-3 text-xs">
    {motion && <p className="mb-2 text-amber-100">{t('templateComponent.motionNotice', { motion: motionWord })}</p>}
    <button type="button" onClick={() => void copy()} className="rounded border border-cyan-400/40 px-3 py-1.5">{t('templateComponent.copyContract')}</button>
    <details className="mt-2"><summary>{t('templateComponent.viewComponents')}</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[10px]">{contract}</pre></details>
    {message && <p role="status" className="mt-2">{message}</p>}
  </div>
}
