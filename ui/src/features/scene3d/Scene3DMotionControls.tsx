import { useUiTranslation } from '../../i18n'
import type { Scene3DSlot, Vec3 } from './types'
import { isWalkBaked } from './walkPath'

type WalkControl = { sceneDuration: number; baking: boolean; error?: string; onBake: () => void }

export function Scene3DMotionControls({ slot, duration, disabled, onChange, walk }: {
  slot: Scene3DSlot; duration: number; disabled?: boolean; onChange: (patch: Partial<Scene3DSlot>) => void; walk?: WalkControl
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const motion = slot.motion
  const distance = motion ? Math.hypot(...motion.to.map((n, i) => n - slot.position[i])) : 0
  return <fieldset disabled={disabled} className="rounded-lg border border-border p-3 text-xs disabled:opacity-50">
    <label className="flex min-h-9 items-center gap-2 font-semibold"><input type="checkbox" checked={Boolean(motion)} onChange={event => onChange({ motion: event.target.checked ? { to: [slot.position[0], slot.position[1], slot.position[2] + 5], faceTravel: true, easing: 'linear' } : undefined })} />{t('travel.title')}</label>
    <div className="flex flex-wrap gap-4">
      <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={Boolean(slot.grounded)} onChange={event => onChange({ grounded: event.target.checked })} />{t('travel.ground')}</label>
      <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={slot.performance === 'typing'} onChange={event => onChange({ performance: event.target.checked ? 'typing' : undefined })} />{t('travel.typing')}</label>
    </div>
    {slot.performance === 'typing' && <p className="my-2 text-text-muted">{t('travel.typingHelp')}</p>}
    {motion && <>
      <p className="my-2 text-text-muted">{t('travel.help')}</p>
      {(['to', ...(motion.via ? ['via' as const] : [])] as const).map(key => <div key={key} className="mb-2 flex flex-wrap items-center gap-2">
        <span>{t(`travel.${key}`)}</span>
        {(['X', 'Y', 'Z'] as const).map((axis, index) => <label key={axis}>{axis}<input aria-label={`${t(`travel.${key}`)} ${axis}`} type="number" step="0.25" value={motion[key]![index]} onChange={event => { const n = event.target.valueAsNumber; if (!Number.isFinite(n)) return; const next = [...motion[key]!] as [number, number, number]; next[index] = n; onChange({ motion: { ...motion, [key]: next } }) }} className="ml-1 min-h-9 w-20 rounded border border-border bg-bg-tertiary px-2" /></label>)}
      </div>)}
      <div className="flex flex-wrap gap-4">
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={Boolean(motion.faceTravel)} onChange={event => onChange({ motion: { ...motion, faceTravel: event.target.checked } })} />{t('travel.face')}</label>
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={Boolean(motion.via)} onChange={event => onChange({ motion: { ...motion, via: event.target.checked ? slot.position.map((v, i) => (v + motion.to[i]) / 2 + (i === 0 ? 2 : 0)) as unknown as Vec3 : undefined } })} />{t('travel.curve')}</label>
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={motion.easing === 'smooth'} onChange={event => onChange({ motion: { ...motion, easing: event.target.checked ? 'smooth' : 'linear' } })} />{t('travel.ease')}</label>
      </div>
      <p className="text-text-muted">{t('travel.distance', { distance: distance.toFixed(1), speed: (distance / Math.max(.1, duration)).toFixed(1) })}</p>
      {walk && slot.media === 'model3d' && <WalkBake slot={slot} walk={walk} />}
    </>}
  </fieldset>
}

function WalkBake({ slot, walk }: { slot: Scene3DSlot; walk: WalkControl }) {
  const { t } = useUiTranslation('scene3dEditor')
  const baked = isWalkBaked(slot, walk.sceneDuration)
  const stale = Boolean(slot.motion?.walk) && !baked
  return <div className="mt-2 space-y-1 border-t border-border pt-2">
    <button type="button" disabled={walk.baking} onClick={walk.onBake} className="min-h-9 rounded border border-border px-3 text-xs hover:border-accent-blue disabled:opacity-50">
      {walk.baking ? t('travel.walkBaking') : t('travel.walk')}
    </button>
    <p className="text-text-muted">{baked ? t('travel.walkReady') : stale ? t('travel.walkStale') : t('travel.walkHelp')}</p>
    {walk.error && <p className="text-red-300">{walk.error}</p>}
  </div>
}
