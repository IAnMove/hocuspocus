import { lazy, Suspense, useRef, useState } from 'react'
import type { ApiOutput } from '../../api/outputs'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { imageBatchPairs, MAX_IMAGE_BATCH_JOBS } from '../../features/studio/imageBatch'
import { forgetLocalImage, rememberLocalImage } from '../../lib/localEditImages'
import { setStudioImageMask } from '../../features/studio/imageInputActions'

const AssetExplorerDialog = lazy(() => import('../common/AssetExplorerDialog').then(module => ({ default: module.AssetExplorerDialog })))

export function ImageBatchControls() {
  const { t } = useUiTranslation('studio')
  const { t: common } = useUiTranslation('common')
  const settings = useStore(state => state.imageBatch)
  const workspace = useStore(state => state.activeWorkspace)
  const edit = useStore(state => state.imageStudioIntent === 'edit')
  const prompt = useStore(state => String(state.params.prompt || ''))
  const mask = useStore(state => state.params.image_mask)
  const [open, setOpen] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const sources = settings?.sources ?? []
  const enabled = edit && Boolean(settings?.enabled)
  const patch = (value: Partial<NonNullable<typeof settings>>) => useStore.setState(state => ({
    imageBatch: { enabled: false, perLine: false, sources: [], ...state.imageBatch, ...value },
  }))
  const add = (items: ApiOutput[]) => {
    const next = [...sources]
    for (const item of items) if (!next.some(other => other.url === item.url)) next.push(item)
    patch({ sources: next })
  }
  const count = imageBatchPairs(prompt, settings, edit).length
  return <section className="space-y-2 rounded border border-border p-2" aria-label={t('imageBatch.title')}>
    <label className="flex items-center justify-between gap-2 text-xs">
      {t('imageBatch.promptMode')}
      <select aria-label={t('imageBatch.promptMode')} value={settings?.perLine ? 'lines' : 'whole'} onChange={event => patch({ perLine: event.target.value === 'lines' })} className="rounded bg-bg-tertiary p-1">
        <option value="whole">{t('imageBatch.whole')}</option>
        <option value="lines">{t('imageBatch.lines')}</option>
      </select>
    </label>
    {edit && <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={enabled} onChange={event => patch({ enabled: event.target.checked })} />{t('imageBatch.enable')}</label>}
    {enabled && <>
      <div className="flex gap-2 text-xs">
        <button type="button" className="rounded border border-border p-2" onClick={() => input.current?.click()}>{common('picker.fromDevice')}</button>
        <button type="button" className="rounded border border-border p-2" onClick={() => setOpen(true)}>{common('picker.fromLibrary')}</button>
      </div>
      <input ref={input} type="file" accept="image/*" multiple className="hidden" data-testid="image-batch-files" onChange={event => {
        const files = [...(event.target.files || [])].filter(file => file.type.startsWith('image/'))
        add(files.map(file => ({ name: file.name, type: 'image', mode: null, size: file.size, created_at: Date.now() / 1000, url: rememberLocalImage(file) })))
        event.target.value = ''
      }} />
      <ul className="max-h-40 space-y-1 overflow-auto text-xs">
        {sources.map(item => <li key={item.url} className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate">{item.name}</span><button type="button" aria-label={common('picker.remove') + ' ' + item.name} onClick={() => {
          forgetLocalImage(item.url)
          patch({ sources: sources.filter(other => other.url !== item.url) })
        }}>×</button></li>)}
      </ul>
      {mask && <div role="alert" className="text-xs text-amber-300">{t('imageBatch.noMask')} <button type="button" onClick={() => setStudioImageMask(undefined)}>{common('picker.remove')}</button></div>}
      <Suspense fallback={null}>{open && <AssetExplorerDialog open title={t('imageBatch.title')} items={[]} workspaceId={workspace} remote constraints={{ kinds: ['image'], maxCount: MAX_IMAGE_BATCH_JOBS, optional: false }} onChoose={() => {}} onChooseMany={add} onClose={() => setOpen(false)} />}</Suspense>
    </>}
    {(enabled || settings?.perLine) && <p role="status" className="text-xs text-text-secondary">{t('imageBatch.count', { count })} {t('imageBatch.hint')}</p>}
    {count > MAX_IMAGE_BATCH_JOBS && <p role="alert" className="text-xs text-amber-300">{t('imageBatch.limit', { count: MAX_IMAGE_BATCH_JOBS })}</p>}
  </section>
}
