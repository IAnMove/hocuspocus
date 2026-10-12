import { useUiTranslation } from '../../../i18n'
import type { Scene3DDocument } from '../types'
import { DEFAULT_MOTION_LAB, isMotionLab, type MotionLabSettings } from './types'

export function MotionLabControls({ document, disabled, onChange }: {
  document: Scene3DDocument; disabled: boolean; onChange: (settings: MotionLabSettings) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!isMotionLab(document.dressing)) return null
  const settings = document.motionLab ?? DEFAULT_MOTION_LAB
  const patch = (value: Partial<MotionLabSettings>) => onChange({ ...settings, ...value })
  const musical = document.dressing === 'motion-bouncing-ball' || document.dressing === 'motion-music-machine'
  return <fieldset disabled={disabled} className="rounded-lg border border-border p-3" data-testid="motion-lab-controls">
    <legend>{t('motionLab.controls')}</legend>
    <div className="flex flex-wrap gap-3 text-sm">
      {musical && <label>{t('motionLab.bpm')}<input aria-label={t('motionLab.bpm')} type="number" min={40} max={240} value={settings.bpm} onChange={event => { const bpm = Number(event.target.value); if (bpm >= 40 && bpm <= 240) patch({ bpm }) }} /></label>}
      <label>{t('motionLab.speed')}<input aria-label={t('motionLab.speed')} type="range" min={.1} max={3} step={.1} value={settings.speed} onChange={event => patch({ speed: Number(event.target.value) })} /></label>
      <label>{t('motionLab.amplitude')}<input aria-label={t('motionLab.amplitude')} type="range" min={.1} max={3} step={.1} value={settings.amplitude} onChange={event => patch({ amplitude: Number(event.target.value) })} /></label>
      <label>{t('motionLab.color')}<input aria-label={t('motionLab.color')} type="color" value={settings.color} onChange={event => patch({ color: event.target.value })} /></label>
      <label>{t('motionLab.secondaryColor')}<input aria-label={t('motionLab.secondaryColor')} type="color" value={settings.secondaryColor} onChange={event => patch({ secondaryColor: event.target.value })} /></label>
      <label>{t('motionLab.seed')}<input aria-label={t('motionLab.seed')} type="number" min={0} max={2147483647} value={settings.seed} onChange={event => { const seed = Number(event.target.value); if (Number.isInteger(seed) && seed >= 0 && seed <= 2147483647) patch({ seed }) }} /></label>
      {(document.dressing === 'motion-poster-breakout' || document.dressing === 'motion-particle-morph') && <label>{t('motionLab.title')}<input aria-label={t('motionLab.title')} maxLength={24} value={settings.title} onChange={event => patch({ title: event.target.value })} /></label>}
      {document.dressing === 'motion-particle-morph' && <label>{t('motionLab.density')}<input aria-label={t('motionLab.density')} type="range" min={200} max={3000} step={100} value={settings.density} onChange={event => patch({ density: Number(event.target.value) })} /></label>}
      {musical && <><label><input type="checkbox" checked={settings.sound} onChange={event => patch({ sound: event.target.checked })} />{t('motionLab.sound')}</label>
        <label>{t('motionLab.volume')}<input aria-label={t('motionLab.volume')} type="range" min={0} max={1} step={.05} value={settings.volume} onChange={event => patch({ volume: Number(event.target.value) })} /></label></>}
    </div>
  </fieldset>
}
