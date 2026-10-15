import { useState } from 'react'
import { WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { customAnimationDef, customViews, MAX_CUSTOM_POSES, MAX_CUSTOM_TEXT, type AnimationDef, type CustomView } from '../../lib/characterAnimations'

const field = 'mt-1 w-full rounded-lg border border-border bg-bg-primary px-3 text-xs disabled:opacity-40'

/** An animation the author invents: a name, the framing and one line per pose. The character's own picture is its reference, like
 * the catalog's; the animation is kept on the kit with the words of each pose, so one pose can be made again alone. */
export function CustomAnimationForm({ disabled, freeId, onCreate }: { disabled: boolean; freeId: (name: string) => string; onCreate: (def: AnimationDef) => void }) {
  const { t } = useUiTranslation('characters')
  const [name, setName] = useState('')
  const [view, setView] = useState<CustomView>('bust')
  const [poses, setPoses] = useState('')
  const lines = poses.split('\n').map(line => line.trim()).filter(Boolean)
  const tooMany = lines.length > MAX_CUSTOM_POSES
  const tooLong = lines.some(line => line.length > MAX_CUSTOM_TEXT)
  const ready = Boolean(name.trim()) && lines.length > 0 && !tooMany && !tooLong
  return <form data-testid="custom-animation-form" className="space-y-2 rounded-lg border border-dashed border-border p-3"
    onSubmit={event => { event.preventDefault(); if (ready && !disabled) { onCreate(customAnimationDef(freeId(name), name.trim(), view, lines)); setName(''); setPoses('') } }}>
    <h5 className="text-sm font-medium">{t('animations.custom.title')}</h5>
    <p className="text-[11px] text-text-muted">{t('animations.custom.hint', { max: MAX_CUSTOM_POSES })}</p>
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-xs text-text-secondary">{t('animations.custom.name')}
        <input value={name} maxLength={40} disabled={disabled} onChange={event => setName(event.target.value)} className={`${field} min-h-9`} /></label>
      <label className="text-xs text-text-secondary">{t('animations.custom.view')}
        <select value={view} disabled={disabled} onChange={event => setView(event.target.value as CustomView)} className={`${field} min-h-9`}>
          {customViews.map(item => <option key={item} value={item}>{t(`animations.view.${item}`)}</option>)}
        </select></label>
    </div>
    <label className="block text-xs text-text-secondary">{t('animations.custom.poses')}
      <textarea value={poses} rows={4} disabled={disabled} onChange={event => setPoses(event.target.value)} placeholder={t('animations.custom.placeholder')} className={`${field} p-3`} /></label>
    {(tooMany || tooLong) && <p role="alert" className="text-[11px] text-red-300">{t(tooMany ? 'animations.custom.tooMany' : 'animations.custom.tooLong', { max: tooMany ? MAX_CUSTOM_POSES : MAX_CUSTOM_TEXT })}</p>}
    <button type="submit" disabled={disabled || !ready} className="inline-flex min-h-8 items-center gap-1 rounded-md border border-border px-2 text-[11px] text-cyan-200 disabled:opacity-40">
      <WandSparkles size={12} />{t('animations.custom.create', { count: lines.length })}</button>
  </form>
}
