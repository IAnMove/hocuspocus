import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { WangpMediaInput } from './WangpMediaInput'
import { WangpInjectedFrame } from './WangpFrameInputs'

export function WangpAdvancedControls() {
  const { t } = useUiTranslation('studio')
  const capabilities = useStore(s => s.modelOptions?.wangp_1272_capabilities)
  const supported = useStore(s => s.modelOptions?.wangp_1272)
  const settings = useStore(s => s.modelOptions?.custom_settings_def)
  const model = useStore(s => String(s.params.model_type || ''))
  const params = useStore(s => s.params)
  const setParams = useStore(s => s.setParams)
  const setParam = useStore(s => s.setParam)
  if (!supported || capabilities?.viggle) return null
  const isFl = model.includes('fl2va') || capabilities?.vdn
  const flags = String(params.video_prompt_type || '')
  const phases = Number(params.guidance_phases || 1)
  return <section className="space-y-2 border border-border rounded-lg p-3" aria-label="WanGP options">
    <p className="text-xs font-medium">{model.startsWith('sensenova') ? 'SenseNova U1.5' : 'H3 Advanced'}</p>
    {settings?.filter(setting => setting.type === 'dropdown').map(setting => <label key={setting.id} className="block text-xs">{setting.name}
      <select aria-label={setting.name} className="w-full bg-bg-tertiary rounded p-2" value={String((params.custom_settings as Record<string, unknown> | undefined)?.[setting.id] ?? setting.default ?? '')} onChange={event => setParam('custom_settings', { ...(params.custom_settings || {}), [setting.id]: event.target.value })}>
        {setting.choices?.map(([label, value]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>)}
    {capabilities?.two_phase && <label className="block text-xs">{t('wangp.phases')}
      <select aria-label={t('wangp.phases')} className="w-full bg-bg-tertiary rounded p-2" value={phases === 2 ? flags.includes('~') ? 'tiles' : 'two' : 'one'} onChange={event => {
        const choice = event.target.value
        setParams({ guidance_phases: choice === 'one' ? 1 : 2, video_prompt_type: flags.replaceAll('~', '') + (choice === 'tiles' ? '~' : ''), switch_threshold: 0.9 })
      }}>
        <option value="one">{t('wangp.onePhase')}</option><option value="two">{t('wangp.twoPhases')}</option><option value="tiles">{t('wangp.tiledPhase')}</option>
      </select>
    </label>}
    {phases === 2 && <p className="text-[11px] text-text-muted">{t('wangp.phaseHint')}</p>}
    {isFl && <>
      <label className="flex items-center gap-2 text-xs"><input aria-label={t('wangp.injectedFrame')} type="checkbox" checked={flags.includes('KFI')} onChange={event => {
        useStore.setState({ imageRefs: [] })
        setParams({ video_guide: '', video_mask: '', image_refs: [], frames_positions: '0', video_prompt_type: (event.target.checked ? 'KFI' : '') + (flags.includes('~') ? '~' : '') })
      }} />{t('wangp.injectedFrame')}</label>
      {flags.includes('KFI') ? <WangpInjectedFrame /> : <>
      <WangpMediaInput label={t('wangp.controlVideo')} kind="video" path={String(params.video_guide || '')} onChoose={item => setParams({ video_guide: item?.url || '', video_prompt_type: item ? `GV${flags.includes('~') ? '~' : ''}` : flags.replace(/[GVAN]/g, '') })} />
      {!!params.video_guide && <>
        <WangpMediaInput label={t('wangp.maskVideo')} kind="video" path={String(params.video_mask || '')} onChoose={item => setParams({ video_mask: item?.url || '', video_prompt_type: flags.replace(/[AN]/g, '') + (item ? 'A' : '') })} />
        <label className="block text-xs">{t('wangp.denoising')}<input aria-label={t('wangp.denoising')} type="range" min="0" max="1" step="0.05" value={Number(params.denoising_strength ?? 0.75)} onChange={event => setParam('denoising_strength', Number(event.target.value))} /></label>
        <label className="block text-xs">{t('wangp.outpaintMargins')}<input aria-label={t('wangp.outpaintMargins')} className="w-full bg-bg-tertiary rounded p-2" placeholder="0 0 0 0" value={String(params.video_guide_outpainting || '')} onChange={event => setParam('video_guide_outpainting', event.target.value)} /></label>
        <p className="text-[11px] text-text-muted">{t('wangp.maskHint')}</p>
      </>}
      </>}
    </>}
  </section>
}
