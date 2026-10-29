import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { comicTransitionBody } from './comicTransition'

/** Builds the two comic-page scenes through the same command the Wizard and MCP call. */
export function ComicTransitionPanel({ workspace, disabled }: { workspace?: string; disabled?: boolean }) {
  const { t } = useUiTranslation('scene3dEditor')
  const [format, setFormat] = useState<'landscape' | 'portrait'>('portrait')
  const [fromPanel, setFromPanel] = useState(0)
  const [toPanel, setToPanel] = useState(3)
  const [images, setImages] = useState(['', '', '', ''])
  const [times, setTimes] = useState(['', '', '', ''])
  const [exportClips, setExportClips] = useState(false)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    if (!workspace || busy) return
    setBusy(true)
    setStatus('')
    const panels = images.map((image, index) => {
      const at = times[index].trim()
      return at ? { video: image, at: Number(at) } : image
    })
    const body = comicTransitionBody({
      workspace, format, panels, fromPanel, toPanel, exportClips,
      intentId: `ui-comic-${Date.now().toString(36)}`,
    })
    try {
      const response = await fetch('/api/v1/world3d/templates/commands', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': 'wizard' },
        body: JSON.stringify(body),
      })
      const payload = await response.json() as { result?: { scenes?: Array<{ role?: string; sceneId?: string }> }; detail?: { message?: string } }
      if (!response.ok) throw new Error(payload.detail?.message || t('comicTransition.failed'))
      const scenes = payload.result?.scenes ?? []
      setStatus(scenes.map(scene => `${scene.role ?? ''} ${scene.sceneId ?? ''}`.trim()).join(', ') || t('comicTransition.done'))
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t('comicTransition.failed'))
    } finally {
      setBusy(false)
    }
  }

  const setImage = (index: number, value: string) => setImages(current => current.map((item, at) => at === index ? value : item))
  const setTime = (index: number, value: string) => setTimes(current => current.map((item, at) => at === index ? value : item))
  return <details className="rounded-lg border border-border p-3">
    <summary className="cursor-pointer text-sm font-semibold">{t('comicTransition.title')}</summary>
    <fieldset disabled={disabled || busy || !workspace} className="mt-2 space-y-2 text-xs disabled:opacity-50">
      <p className="text-text-muted">{t('comicTransition.help')}</p>
      <label className="flex items-center gap-2">{t('comicTransition.format')}
        <select aria-label={t('comicTransition.format')} className="rounded border border-border bg-bg-tertiary p-2" value={format} onChange={event => setFormat(event.target.value as 'landscape' | 'portrait')}>
          <option value="landscape">{t('comicTransition.landscape')}</option>
          <option value="portrait">{t('comicTransition.portrait')}</option>
        </select>
      </label>
      <div className="flex flex-wrap gap-3">
        <label>{t('comicTransition.from')}<input aria-label={t('comicTransition.from')} type="number" min={0} max={3} value={fromPanel} onChange={event => setFromPanel(event.target.valueAsNumber)} className="ml-2 w-16 rounded border border-border bg-bg-tertiary p-2" /></label>
        <label>{t('comicTransition.to')}<input aria-label={t('comicTransition.to')} type="number" min={0} max={3} value={toPanel} onChange={event => setToPanel(event.target.valueAsNumber)} className="ml-2 w-16 rounded border border-border bg-bg-tertiary p-2" /></label>
      </div>
      {images.map((image, index) => <div key={index} className="flex flex-wrap gap-2">
        <label className="min-w-0 flex-1">{t('comicTransition.panel')} {index}
          <input aria-label={`${t('comicTransition.panel')} ${index}`} value={image} onChange={event => setImage(index, event.target.value)} className="ml-2 w-full min-w-40 rounded border border-border bg-bg-tertiary p-2" placeholder={t('comicTransition.image')} />
        </label>
        <label>{t('comicTransition.at')}<input aria-label={`${t('comicTransition.at')} ${index}`} value={times[index]} onChange={event => setTime(index, event.target.value)} className="ml-2 w-20 rounded border border-border bg-bg-tertiary p-2" /></label>
      </div>)}
      <label className="flex items-center gap-2"><input aria-label={t('comicTransition.export')} type="checkbox" checked={exportClips} onChange={event => setExportClips(event.target.checked)} />{t('comicTransition.export')}</label>
      <button type="button" className="min-h-9 rounded border border-border px-3" onClick={() => void run()}>{busy ? t('comicTransition.working') : t('comicTransition.run')}</button>
      {status && <p>{status}</p>}
    </fieldset>
  </details>
}
