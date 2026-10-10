import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { buttonClass } from './styles'

export function GlbPreview({ url, clips }: { url: string; clips: string[] }) {
  const { t } = useUiTranslation('gameAssets')
  const [clip, setClip] = useState(clips[0] || '')
  useEffect(() => { void import('@google/model-viewer') }, [])
  if (!url) return null
  return (
    <div className="space-y-2">
      <model-viewer src={url} alt="" camera-controls autoplay animation-name={clip || undefined} style={{ width: '100%', height: '240px' }} />
      {clips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm">{t('clips')}</span>
          {clips.map(item => (
            <button key={item} type="button" className={buttonClass} aria-pressed={item === clip} onClick={() => setClip(item)}>{item}</button>
          ))}
        </div>
      )}
    </div>
  )
}
