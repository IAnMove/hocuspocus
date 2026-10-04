import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FORMAT_KEYS, LIGHT_FORMATS, type LightFormat } from './types'

export function LightCreate({ onCreate }: {
  onCreate: (body: { intent_id: string, format: LightFormat, title: string }) => void
}) {
  const { t } = useTranslation('productionCatalog')
  const intent = useRef<string | null>(null)
  const [title, setTitle] = useState('')
  const [format, setFormat] = useState<LightFormat>('music_video')
  return <form className="mb-4 rounded border border-border p-3" onSubmit={event => {
    event.preventDefault()
    if (!intent.current) intent.current = `ui-${globalThis.crypto.randomUUID()}`
    onCreate({ intent_id: intent.current, format, title: title.trim() || t('create.untitled') })
  }}>
    <h3 className="text-sm font-semibold">{t('create.title')}</h3>
    <p className="mt-1 text-xs text-text-muted">{t('create.hint')}</p>
    <label className="mt-2 block text-xs">
      {t('create.name')}
      <input className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1" value={title} onChange={event => setTitle(event.target.value)} />
    </label>
    <div className="mt-2 flex flex-wrap gap-2">
      {LIGHT_FORMATS.map(item => <button key={item} type="button" className={`rounded border px-2 py-1 text-xs ${item === format ? 'border-border bg-bg-tertiary' : 'border-border'}`} data-format={item} onClick={() => setFormat(item)}>{t(FORMAT_KEYS[item])}</button>)}
    </div>
    <button type="submit" className="mt-2 rounded border border-border px-2 py-1 text-xs">{t('create.submit')}</button>
  </form>
}
