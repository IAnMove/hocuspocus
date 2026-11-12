import { useEffect, useState } from 'react'
import { BASE } from '../../../api/http'
import { useUiTranslation } from '../../../i18n'

export function VocalIsolationOption({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    void fetch(`${BASE}/api/v1/character-kits/speech/capabilities`, { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error('capabilities')
      const data = await response.json()
      if (!abort.signal.aborted) setState(data.vocalIsolation?.available ? 'ready' : 'missing')
    }).catch(() => { if (!abort.signal.aborted) setState('error') })
    return () => abort.abort()
  }, [retry])
  return <div className="space-y-1 text-xs">
    <label className="flex min-h-10 items-center gap-2"><input aria-label={t('speech.isolation.label')} type="checkbox" checked={checked} disabled={!checked && state !== 'ready'} onChange={event => onChange(event.target.checked)} />{t('speech.isolation.label')}</label>
    <p className="text-text-muted">{t(`speech.isolation.${state}`)}</p>
    {state === 'error' && <button type="button" onClick={() => setRetry(value => value + 1)}>{t('speech.isolation.retry')}</button>}
  </div>
}
