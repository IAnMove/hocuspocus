import type { ApiOutput } from '../../api/client'
import { AssetInput } from '../asset-picker/AssetInput'
import { useUiTranslation } from '../../i18n'
import { MAX_IMAGE_POSES, type ImagePose } from './imagePoseSequence'
import type { MediaScreen } from './mediaScreen'
import { pickerOutputFromSlot, sourceRefFromOutput } from './slotSource'

export function Scene3DPoseSequenceControls({ screen, baseUrl, items, disabled, workspace, onChange }: {
  screen: MediaScreen; baseUrl: string; items: ApiOutput[]; disabled: boolean; workspace?: string
  onChange: (screen: MediaScreen) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const poses = screen.poseSequence
  const update = (next: ImagePose[]) => onChange({ ...screen, media: 'image', transparent: true,
    sourceUrl: next[0]?.sourceUrl || baseUrl, sourceRef: next[0]?.sourceRef, poseSequence: next.length ? next : undefined })
  const create = (sourceUrl: string): ImagePose => ({ sourceUrl, duration: 1, height: .9, x: 0, lift: .02 })
  const swap = (index: number, offset: number) => {
    const next = [...poses!]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; update(next)
  }
  return <div className="space-y-3" data-testid="scene3d-pose-controls">
    <label className="flex min-h-10 items-center gap-2"><input type="checkbox" disabled={disabled || (!poses && !baseUrl && !screen.sourceUrl)} checked={Boolean(poses)}
      onChange={event => event.target.checked ? update([create(baseUrl || screen.sourceUrl)]) : onChange({ ...screen, poseSequence: undefined })} />{t('poses.enable')}</label>
    {poses && <>
      <p className="text-xs text-text-muted">{t('poses.help')}</p>
      {poses.map((pose, index) => <fieldset key={`${index}:${pose.sourceUrl}`} className="space-y-2 rounded border border-border p-3">
        <legend className="px-1 text-sm">{t('poses.number', { count: index + 1 })}</legend>
        <AssetInput label={t('poses.image')} placeholder={t('poses.choose')} items={items.filter(item => item.type === 'image')}
          value={pickerOutputFromSlot(pose.sourceUrl, 'image', pose.sourceRef)} accept="image/*" disabled={disabled} workspaceId={workspace}
          constraints={{ kinds: ['image'], maxCount: 1, optional: false }} onChoose={item => {
            if (!item || disabled || item.type !== 'image') return
            update(poses.map((p, i) => i === index ? { ...p, sourceUrl: item.url, sourceRef: sourceRefFromOutput(item, workspace || 'default') } : p))
          }} />
        <div className="grid grid-cols-2 gap-3">
          {(['duration', 'height', 'x', 'lift'] as const).map(key => <label key={key} className="text-xs">{t(`poses.${key}`)}
            <input type="number" aria-label={`${t(`poses.${key}`)} ${index + 1}`} disabled={disabled} step={key === 'duration' ? .05 : .01}
              min={key === 'duration' ? 1 / 60 : key === 'height' ? .05 : -1} max={key === 'duration' ? 600 : key === 'height' ? 2 : 1} value={pose[key]}
              onChange={event => { const value = Number(event.target.value); if (!event.target.value || !Number.isFinite(value)) return
                const min = key === 'duration' ? 1 / 60 : key === 'height' ? .05 : -1, max = key === 'duration' ? 600 : key === 'height' ? 2 : 1
                update(poses.map((p, i) => i === index ? { ...p, [key]: Math.max(min, Math.min(max, value)) } : p))
              }} className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary p-2" />
          </label>)}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="min-h-9 rounded border border-border px-2" disabled={disabled || index === 0} onClick={() => swap(index, -1)}>{t('poses.earlier')}</button>
          <button type="button" className="min-h-9 rounded border border-border px-2" disabled={disabled || index === poses.length - 1} onClick={() => swap(index, 1)}>{t('poses.later')}</button>
          <button type="button" className="min-h-9 rounded border border-border px-2" disabled={disabled || poses.length <= 1} onClick={() => update(poses.filter((_, i) => i !== index))}>{t('poses.remove')}</button>
        </div>
      </fieldset>)}
      <button type="button" disabled={disabled || poses.length >= MAX_IMAGE_POSES} onClick={() => update([...poses, { ...poses[poses.length - 1] }])} className="min-h-10 rounded border border-border px-3">{t('poses.add')}</button>
    </>}
  </div>
}
