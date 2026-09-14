import { useRef, useState } from 'react'
import { ImagePlus, Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { generateSeriesReferenceImage, pendingSeriesImage, prepareSeriesLocationPrompt, seriesImageJobKey, seriesReferencePrompt } from './referenceImages'
import type { SeriesReferenceImport, SeriesReferenceTarget } from './referenceImages'
import type { SeriesProject } from './types'
import { secondaryButton, textareaClass } from './styles'

export function SeriesReferenceGenerator({ workspace, series, target, saveNow, onImported }: {
  workspace: string; series: SeriesProject; target: SeriesReferenceTarget
  saveNow: () => Promise<unknown>; onImported: (workspace: string, result: SeriesReferenceImport) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const [promptOverride, setPrompt] = useState('')
  const prompt = promptOverride || seriesReferencePrompt(series, target)
  const [busy, setBusy] = useState(false)
  const [preparingPrompt, setPreparingPrompt] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(() => pendingSeriesImage(seriesImageJobKey(workspace, series.id, target)))
  const promptLocked = busy || Boolean(pending)
  const active = useRef(false)
  const prepareLocation = async () => {
    if (active.current) return
    active.current = true; setBusy(true); setPreparingPrompt(true); setError('')
    try {
      await saveNow()
      setPrompt(await prepareSeriesLocationPrompt(workspace, series, target.id, prompt))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { active.current = false; setBusy(false); setPreparingPrompt(false) }
  }
  const generate = async () => {
    if (active.current) return
    active.current = true; setBusy(true); setError('')
    try {
      await saveNow()
      const result = await generateSeriesReferenceImage(workspace, series, target, {
        prompt, beforeImport: saveNow,
        onPreparingPrompt: () => setPreparingPrompt(true),
        onPromptPrepared: value => { setPrompt(value); setPreparingPrompt(false) },
        onSubmitted: () => setPending(pendingSeriesImage(seriesImageJobKey(workspace, series.id, target))),
      })
      onImported(workspace, result)
      setPending(undefined)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setPending(pendingSeriesImage(seriesImageJobKey(workspace, series.id, target)))
    }
    finally { active.current = false; setBusy(false); setPreparingPrompt(false) }
  }
  return <div className="space-y-2 rounded-lg border border-violet-500/25 p-2">
    <details>
      <summary className="cursor-pointer text-xs text-text-secondary">{t('references.prompt')}</summary>
      <textarea aria-label={t('references.prompt')} className={`${textareaClass} mt-2`} value={pending?.prompt || prompt} disabled={promptLocked} onChange={event => setPrompt(event.target.value)} />
      <div className="mt-1 flex flex-wrap gap-2">
        <button type="button" className={secondaryButton} disabled={promptLocked} onClick={() => setPrompt(seriesReferencePrompt(series, target))}>{t('references.fromDescription')}</button>
        {target.kind === 'location' && <button type="button" className={secondaryButton} disabled={promptLocked} onClick={() => void prepareLocation()}>{t('references.prepareLocation')}</button>}
      </div>
    </details>
    <button type="button" className={secondaryButton} disabled={busy || !prompt.trim()} onClick={() => void generate()}>
      {busy ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
      {preparingPrompt ? t('references.preparingLocation') : busy ? t('references.generating') : pending ? t('references.resume') : t('references.generate')}
    </button>
    <p className="text-[10px] text-text-muted">{t('references.hint')}</p>
    {target.kind === 'location' && <p className="text-[10px] text-text-muted">{t('references.locationHint')}</p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
