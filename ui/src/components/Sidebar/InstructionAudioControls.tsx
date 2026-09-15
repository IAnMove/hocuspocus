import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../../features/asset-picker/AssetInput'
import { studioMediaPath, useWorkspaceOutputs } from '../../lib/studioAssetPick'
import { getStoredAssetUrl } from '../../api/client'
import type { ApiOutput } from '../../api/outputs'

export function InstructionAudioControls() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const workspace = useStore(s => s.activeWorkspace)
  const setParam = useStore(s => s.setParam)
  const filename = useStore(s => s.audioGuideFilename)
  const setFilename = useStore(s => s.setAudioGuideFilename)
  const items = useWorkspaceOutputs(workspace, 'audio')
  const reference = typeof params.audio_guide === 'string' ? params.audio_guide : ''
  const value: ApiOutput | undefined = items.find(item => studioMediaPath(item) === reference) || (reference ? {
    name: filename || reference.split('/').pop() || reference, type: 'audio', mode: null,
    size: 0, created_at: 0, path: reference,
    url: reference.startsWith('/api/') ? reference : getStoredAssetUrl(reference),
  } : undefined)
  const useSource = params.audio_prompt_type === 'A'

  return <div className="space-y-3">
    <label className="block text-xs text-text-secondary">
      {t('auk.mode')}
      <select className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2"
        value={useSource ? 'A' : ''} onChange={event => {
          setParam('audio_prompt_type', event.target.value)
          if (!event.target.value) { setParam('audio_guide', undefined); setFilename(null) }
        }}>
        <option value="">{t('auk.textMode')}</option>
        <option value="A">{t('auk.sourceMode')}</option>
      </select>
    </label>
    {params.model_type === 'auk' && <div className="flex gap-3 text-xs text-text-secondary">
      <label>{t('auk.steps')}
        <input type="number" min={1} max={100} value={params.num_inference_steps ?? 32}
          className="mt-1 w-full rounded border border-border bg-bg-tertiary p-1"
          onChange={event => setParam('num_inference_steps', Number(event.target.value))} />
      </label>
      <label>{t('auk.guidance')}
        <input type="number" min={0} max={10} step={0.1} value={params.guidance_scale ?? 2}
          className="mt-1 w-full rounded border border-border bg-bg-tertiary p-1"
          onChange={event => setParam('guidance_scale', Number(event.target.value))} />
      </label>
    </div>}
    {useSource && <AssetInput label={t('auk.source')} placeholder={t('auk.source')}
      items={items} value={value} accept=".wav,.mp3,.flac,.ogg,.m4a,audio/*"
      workspaceId={workspace} constraints={{ kinds: ['audio'], maxCount: 1, optional: false }}
      onChoose={item => {
        setParam('audio_guide', item ? studioMediaPath(item) : undefined)
        setFilename(item?.name || null)
      }} />}
    <p className="text-xs text-text-muted">{t('auk.hint')}</p>
    <details className="text-xs text-text-muted">
      <summary className="cursor-pointer">{t('auk.examples')}</summary>
      <ul className="list-disc space-y-2 pl-4 pt-2">
        {(['create', 'clone', 'edit', 'clean', 'separate'] as const).map(key => <li key={key}>{t(`auk.${key}`)}</li>)}
      </ul>
    </details>
    <p className="text-xs text-text-muted">{t('auk.language')}</p>
  </div>
}
