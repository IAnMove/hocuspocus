import { Color } from 'three'
import { useUiTranslation } from '../../../i18n'
import { EXPRESSIONS, type FacePlacement, type Scene3DSpeech } from './types'

export const speechInput = 'min-h-10 rounded border border-border bg-bg-primary px-2 text-xs text-text-primary'
export function SpeechNumber({ label, value, onChange, min = -10000, max = 10000, step = .001 }: {
  label: string; value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number
}) {
  return <label className="flex items-center gap-2 text-xs">{label}<input className={speechInput + ' w-24'} aria-label={label}
    type="number" min={min} max={max} step={step} value={Number(value.toFixed(5))} onChange={event => {
      const next = event.target.valueAsNumber
      if (Number.isFinite(next) && next >= min && next <= max) onChange(next)
    }} /></label>
}
export function FaceControls({ speech, onChange, initiallyOpen = false }: { speech: Scene3DSpeech; onChange: (speech: Scene3DSpeech) => void; initiallyOpen?: boolean }) {
  const { t } = useUiTranslation('scene3dEditor'), face = speech.face
  if (!face) return null
  const change = (patch: Partial<FacePlacement>) => onChange({ ...speech, face: { ...face, ...patch } })
  return <details open={initiallyOpen || undefined} className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm">{t('speech.adjust')}</summary>
    <p className="my-2 text-xs text-text-muted">{t('speech.adjustHint')}</p>
    <div className="flex flex-wrap gap-3">
      {(['x', 'y', 'z'] as const).map((axis, index) => <SpeechNumber key={axis} label={t('speech.mouth') + ' ' + axis.toUpperCase()} value={face.center[index]}
        onChange={value => { const center = [...face.center] as [number, number, number]; center[index] = value; change({ center }) }} />)}
      <SpeechNumber label={t('speech.width')} value={face.size[0]} min={.0001} onChange={value => change({ size: [value, face.size[1]] })} />
      <SpeechNumber label={t('speech.height')} value={face.size[1]} min={.0001} onChange={value => change({ size: [face.size[0], value] })} />
      <SpeechNumber label={t('speech.mesh')} value={face.meshIndex} min={0} max={1023} step={1} onChange={meshIndex => change({ meshIndex })} />
      <label className="flex items-center gap-2 text-xs">{t('speech.skin')}<input type="color" value={'#' + new Color().fromArray(face.skin).getHexString()} onChange={e => change({ skin: new Color(e.target.value).toArray() as [number, number, number] })} /></label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={speech.clean} onChange={e => onChange({ ...speech, clean: e.target.checked })} />{t('speech.clean')}</label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={speech.morph === true} onChange={e => onChange({ ...speech, morph: e.target.checked })} />{t('speech.morph')}</label>
      <SpeechNumber label={t('speech.strength')} value={speech.strength} min={0} max={1.5} step={.05} onChange={strength => onChange({ ...speech, strength })} />
      <label className="flex items-center gap-2 text-xs">{t('speech.style')}<select className={speechInput} value={speech.style} onChange={e => onChange({ ...speech, atlas: undefined, style: e.target.value as Scene3DSpeech['style'] })}>
        {(['soft', 'toon', 'toon-bold', 'pixel'] as const).map(style => <option key={style} value={style}>{t(`speech.${style}`)}</option>)}</select></label>
      <label className="flex items-center gap-2 text-xs">{t('speech.lip')}<input type="color" value={speech.lip} onChange={e => onChange({ ...speech, lip: e.target.value, atlas: undefined })} /></label>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <label className="text-xs"><input type="checkbox" checked={speech.eyes} onChange={e => onChange({ ...speech, eyes: e.target.checked })} /> {t('speech.eyes')}</label>
      <label className="text-xs"><input type="checkbox" checked={speech.blink} onChange={e => onChange({ ...speech, blink: e.target.checked })} /> {t('speech.blink')}</label>
      <select aria-label={t('speech.expressionLabel')} className={speechInput} value={speech.expression} onChange={e => onChange({ ...speech, expression: e.target.value as Scene3DSpeech['expression'] })}>
        {EXPRESSIONS.map(expression => <option key={expression} value={expression}>{t(`speech.expression.${expression}`)}</option>)}</select>
      <SpeechNumber label={t('speech.eyeY')} value={face.eyes.left[1]} onChange={value => {
        const delta = value - face.eyes.left[1]
        change({ eyes: { ...face.eyes, left: [face.eyes.left[0], value, face.eyes.left[2]], right: [face.eyes.right[0], face.eyes.right[1] + delta, face.eyes.right[2]] } })
      }} />
      <SpeechNumber label={t('speech.eyeSpacing')} value={face.eyes.right[0] - face.eyes.left[0]} min={.0001} onChange={value => {
        const middle = (face.eyes.left[0] + face.eyes.right[0]) / 2
        change({ eyes: { ...face.eyes, left: [middle - value / 2, face.eyes.left[1], face.eyes.left[2]], right: [middle + value / 2, face.eyes.right[1], face.eyes.right[2]] } })
      }} />
      <SpeechNumber label={t('speech.eyeWidth')} value={face.eyes.size[0]} min={.0001} onChange={value => change({ eyes: { ...face.eyes, size: [value, face.eyes.size[1]] } })} />
      <SpeechNumber label={t('speech.eyeHeight')} value={face.eyes.size[1]} min={.0001} onChange={value => change({ eyes: { ...face.eyes, size: [face.eyes.size[0], value] } })} />
    </div>
  </details>
}
