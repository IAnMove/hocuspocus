import { useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import { FACE_PROFILES, type FaceProfile, type PlacementMode } from './calibration'
import type { FacePlacement, Scene3DSpeech } from './types'
import { FaceControls, speechInput } from './FaceControls'

export function LipsPlacementControls({ speech, hasModel, calibrate, onChange, onPick }: {
  speech: Scene3DSpeech; hasModel: boolean
  calibrate: (mode: PlacementMode) => FacePlacement | undefined
  onChange: (speech: Scene3DSpeech) => void
  onPick?: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [profile, setProfile] = useState<FaceProfile>('generic')
  const [notice, setNotice] = useState(''), [editing, setEditing] = useState(false)
  const place = (mode: PlacementMode) => {
    const estimated = calibrate(mode), face = estimated ?? calibrate('bounds')
    if (!face) { setNotice(t('speech.noFace')); return }
    onChange({ ...speech, face, enabled: true, eyes: speech.face ? speech.eyes : false, clean: speech.face ? speech.clean : false })
    setEditing(true); setNotice(t(estimated ? 'speech.reviewPlacement' : 'speech.manualPlacement'))
  }
  return <div className="space-y-3" data-testid="speech-lips-placement">
    <button type="button" disabled={!hasModel} className={speechInput + ' border-cyan-400 text-cyan-200'}
      onClick={() => speech.face ? setEditing(value => !value) : place('generic')}>
      {t(speech.face ? 'speech.editLips' : 'speech.addLips')}
    </button>
    {onPick && <button type="button" disabled={!hasModel} className={speechInput} onClick={() => { setEditing(true); onPick() }}>{t('speech.pickLips')}</button>}
    {speech.face && <label className="flex items-center gap-2 text-xs"><input aria-label={t('speech.enabled')} type="checkbox" checked={speech.enabled}
      onChange={event => onChange({ ...speech, enabled: event.target.checked })} />{t('speech.enabled')}</label>}
    {notice && <p role="status" className="text-xs text-amber-200">{notice}</p>}
    {editing && <FaceControls speech={speech} onChange={onChange} initiallyOpen />}
    <details className="rounded border border-border p-2">
      <summary className="cursor-pointer text-xs">{t('speech.placementReferences')}</summary>
      <p className="my-2 text-xs">{t('speech.referencesHint')}</p>
      <div className="flex flex-wrap gap-2">
        <select aria-label={t('speech.profile')} className={speechInput + ' min-w-0 max-w-full'} value={profile}
          onChange={event => setProfile(event.target.value as FaceProfile)}>
          {FACE_PROFILES.map(item => <option key={item} value={item}>{item === 'generic' ? t('speech.generic') : item}</option>)}
        </select>
        <button type="button" disabled={!hasModel} className={speechInput} onClick={() => place(profile)}>{t('speech.calibrate')}</button>
      </div>
    </details>
  </div>
}
