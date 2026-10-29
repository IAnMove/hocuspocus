import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { ContinueVideoSection } from './ContinueVideoSection'
import { WangpMediaInput } from './WangpMediaInput'

/** H3 owns its native media codes; the generic input tiles use other codes. */
export function WangpFrameInputs() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const setParams = useStore(s => s.setParams)
  if (!String(params.model_type).startsWith('h3_advanced')) return null
  return <section className="space-y-2">
    {params.image_mode === 3 ? <ContinueVideoSection /> :
      <WangpMediaInput label={t('wangp.firstFrame')} kind="image" path={String(params.image_start || '')} onChoose={item => {
        useStore.setState({ startImage: null })
        setParams({ image_start: item?.url || '', image_prompt_type: String(params.image_prompt_type || '').replaceAll('S', '') + (item ? 'S' : '') })
      }} />}
    <WangpMediaInput label={t('wangp.lastFrame')} kind="image" path={String(params.image_end || '')} onChoose={item => {
      useStore.setState({ endImage: null })
      setParams({ image_end: item?.url || '', image_prompt_type: String(params.image_prompt_type || '').replaceAll('E', '') + (item ? 'E' : '') })
    }} />
    {!String(params.model_type).includes('ref2va') && <WangpSoundtrack />}
  </section>
}

function WangpSoundtrack() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const setParams = useStore(s => s.setParams)
  const setParam = useStore(s => s.setParam)
  const options = useStore(s => s.modelOptions?.audio_prompt_type_sources)
  return <div className="space-y-2">
    <label className="block text-xs">{t('wangp.audioSource')}
      <select aria-label={t('wangp.audioSource')} className="w-full bg-bg-tertiary rounded p-2" value={String(params.audio_prompt_type || '')} onChange={event => setParam('audio_prompt_type', event.target.value)}>
        {options?.selection?.map(value => <option key={value} value={value}>{options.labels?.[value] || value}</option>)}
      </select>
    </label>
    {String(params.audio_prompt_type).includes('A') && <WangpMediaInput label={t('wangp.soundtrack')} kind="audio" path={String(params.audio_guide || '')} onChoose={item => setParams({ audio_guide: item?.url || '', audio_prompt_type: item ? 'A' : '' })} />}
  </div>
}

export function WangpInjectedFrame() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const setParams = useStore(s => s.setParams)
  const setParam = useStore(s => s.setParam)
  return <div className="space-y-2">
    <WangpMediaInput label={t('wangp.injectedFrame')} kind="image" path={String(params.image_refs?.[0] || '')} onChoose={item => setParams({ image_refs: item ? [item.url] : [] })} />
    <label className="block text-xs">{t('wangp.framePosition')}<input aria-label={t('wangp.framePosition')} className="w-full bg-bg-tertiary rounded p-2" type="number" min="0" step="1" value={String(params.frames_positions || '0')} onChange={event => setParam('frames_positions', event.target.value)} /></label>
  </div>
}
