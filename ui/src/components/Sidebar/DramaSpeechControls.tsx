import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../../features/asset-picker/AssetInput'
import { studioMediaPath, useWorkspaceOutputs } from '../../lib/studioAssetPick'
import { getStoredAssetUrl } from '../../api/client'
import type { ApiOutput } from '../../api/outputs'

export function DramaSpeechControls() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const workspace = useStore(s => s.activeWorkspace)
  const duration = useStore(s => s.durationSeconds)
  const setDuration = useStore(s => s.setDurationSeconds)
  const setParam = useStore(s => s.setParam)
  const items = useWorkspaceOutputs(workspace, 'audio')
  const clone = params.model_type === 'drama3_base'
  const reference = typeof params.audio_guide === 'string' ? params.audio_guide : ''
  const value: ApiOutput | undefined = items.find(item => studioMediaPath(item) === reference) || (reference ? {
    name: reference.split('/').pop() || reference, type: 'audio', mode: null,
    size: 0, created_at: 0, path: reference,
    url: reference.startsWith('/api/') ? reference : getStoredAssetUrl(reference),
  } : undefined)
  return <section className="space-y-3" aria-label="Drama 3">
    {clone && <AssetInput label={t('drama.reference')} placeholder={t('drama.reference')}
      items={items} value={value} accept=".wav,.mp3,.flac,.ogg,.m4a,audio/*"
      workspaceId={workspace} constraints={{ kinds: ['audio'], maxCount: 1, optional: false }}
      onChoose={item => {
        setParam('audio_guide', item ? studioMediaPath(item) : undefined)
        setParam('audio_prompt_type', 'A')
      }} />}
    <label className="block text-xs text-text-secondary">
      {clone ? t('drama.transcript') : t('drama.direction')}
      <textarea aria-label={clone ? t('drama.transcript') : t('drama.direction')} rows={3} required={clone} value={params.alt_prompt || ''}
        className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2"
        onChange={event => setParam('alt_prompt', event.target.value)} />
    </label>
    <p className="text-xs text-text-muted">{t('drama.hint')}</p>
    <label className="block text-xs text-text-secondary">{t('drama.duration')}
      <input aria-label={t('drama.duration')} type="number" min={1} max={180} value={duration}
        className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2"
        onChange={event => setDuration(Number(event.target.value))} />
    </label>
  </section>
}
