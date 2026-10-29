import { useState } from 'react'
import { WangpMediaInput } from '../../components/Sidebar/WangpMediaInput'
import { useUiTranslation } from '../../i18n'

export type WizardVisualMedia = { source: string; kind: 'image' | 'video'; workspace: string }

export function WizardVisualInput({ media, onChange, workspace, disabled, title }: {
  media: WizardVisualMedia | null; onChange: (media: WizardVisualMedia | null) => void; workspace: string; disabled: boolean; title?: string
}) {
  const { t } = useUiTranslation('studio')
  const [kind, setKind] = useState<'image' | 'video'>('image')
  return <details className="mb-2 text-xs">
    <summary>{t('wangp.visualEvidence')}</summary>
    <fieldset disabled={disabled} title={disabled ? title : undefined} className="mt-2 space-y-2">
      <select aria-label={t('wangp.visualKind')} className="bg-bg-tertiary rounded p-1" value={kind} onChange={event => { setKind(event.target.value as 'image' | 'video'); onChange(null) }}>
        <option value="image">{t('wangp.visualImage')}</option><option value="video">{t('wangp.visualVideo')}</option>
      </select>
      <WangpMediaInput label={t('wangp.visualEvidence')} kind={kind} path={media?.source} onChoose={item => onChange(item ? { source: item.url, kind, workspace } : null)} />
      <p className="text-text-muted">{t('wangp.visualHint')}</p>
      <p className="text-text-muted">{t('wangp.visualReadOnly')}</p>
    </fieldset>
  </details>
}
