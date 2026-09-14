import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import { isFaceRigEyeState, type CharacterKitFaceRigState } from '../../lib/characterKitFaceRig'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'

export function FaceRigStatePicker({ kit, selected, disabled, onSelect }: {
  kit: CharacterKit; selected: CharacterKitFaceRigState; disabled: boolean; onSelect: (state: CharacterKitFaceRigState) => void
}) {
  const { t } = useUiTranslation('characters')
  const choice = (state: CharacterKitFaceRigState) => {
    const asset = state === 'open-eyes' ? kit.eyes.open : state === 'blink' ? kit.eyes.blink : kit.mouth[state]
    const label = t(`faceRig.states.${state}`)
    return <button key={state} type="button" disabled={disabled} onClick={() => onSelect(state)}
      className={`rounded border p-2 text-xs ${selected === state ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>
      {label}<span className="block">{isFaceRigEyeState(state) && !asset ? t('faceRig.eyesOriginal') : t(`review.${asset?.reviewState ?? 'missing'}`)}</span>
    </button>
  }
  return <>
    <div className="grid grid-cols-4 gap-2">{(['closed', 'small', 'wide', 'round'] as const).map(choice)}</div>
    {CHARACTER_MOUTH_STATES.slice(4).some(state => kit.mouth[state]) && <div aria-label={t('faceRig.phoneticPositions')} className="grid grid-cols-3 gap-2">
      {CHARACTER_MOUTH_STATES.slice(4).filter(state => kit.mouth[state]).map(choice)}
    </div>}
    <details className="rounded border border-border p-3" onToggle={event => {
      if (!event.currentTarget.open && isFaceRigEyeState(selected)) onSelect('wide')
    }}>
      <summary className="cursor-pointer text-sm">{t('faceRig.optionalEyes')}</summary>
      <p className="my-3 text-xs text-text-secondary">{t('faceRig.optionalEyesHint')}</p>
      <div className="grid grid-cols-2 gap-2">{(['open-eyes', 'blink'] as const).map(choice)}</div>
    </details>
  </>
}
