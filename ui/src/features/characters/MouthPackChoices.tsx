import { useUiTranslation } from '../../i18n'
import { FACE_RIG_PRESET_ROOT, type FaceRigMouthPresetPack } from '../../lib/characterKitFaceRig'

export function MouthPackChoices({ packs, selected, disabled, onSelect, onApply }: {
  packs: FaceRigMouthPresetPack[]; selected: string; disabled: boolean
  onSelect: (id: string) => void; onApply: () => void
}) {
  const { t } = useUiTranslation('characters')
  const pack = packs.find(item => item.id === selected)
  return <section aria-label={t('faceRig.existingMouths')} className="space-y-3 rounded-lg border border-violet-300/30 p-3">
    <h4 className="text-sm font-semibold">{t('faceRig.existingMouths')}</h4>
    <p className="text-xs text-text-secondary">{t('faceRig.packHint')}</p>
    {packs.length ? <>
      <label className="block text-xs">{t('faceRig.mouthPackAria')}
        <select aria-label={t('faceRig.mouthPackAria')} value={selected} disabled={disabled} onChange={event => onSelect(event.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary p-2">
          {packs.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <div className="grid grid-cols-4 gap-2">{(['closed', 'small', 'wide', 'round'] as const).map(state => <figure key={state} className="rounded border border-border bg-bg-primary p-2">
        {pack?.states[state] && <img src={`${FACE_RIG_PRESET_ROOT}/${pack.states[state]!.file}`} alt={t(`mouths.${state}`)} className="h-16 w-full object-contain" />}
        <figcaption className="mt-1 text-center text-xs">{t(`mouths.${state}`)}</figcaption>
      </figure>)}</div>
      <button type="button" disabled={disabled || !pack} onClick={onApply} className="rounded border border-violet-300/40 bg-violet-400/10 px-4 py-2 text-sm text-violet-100 disabled:opacity-40">{t('faceRig.usePack')}</button>
    </> : <p role="status" className="text-xs">{t('faceRig.packsUnavailable')}</p>}
  </section>
}
