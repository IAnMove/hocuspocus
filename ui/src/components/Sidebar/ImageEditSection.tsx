import { useUiTranslation } from '../../i18n'
import { studioImageEditCapabilities } from '../../lib/studioImageEdit'
import { setStudioImageMask, setStudioImageSource } from '../../features/studio/imageInputActions'
import { useStore } from '../../stores/useStore'
import { WangpMediaInput } from './WangpMediaInput'
import { ImageEditControls } from './ImageEditControls'

export function ImageEditSection() {
  const { t } = useUiTranslation('studio')
  const modelOptions = useStore(s => s.modelOptions)
  const params = useStore(s => s.params)
  const setParam = useStore(s => s.setParam)
  const batch = useStore(s => Boolean(s.imageBatch?.enabled))
  const capabilities = studioImageEditCapabilities(modelOptions)
  if (!capabilities) return null
  if (!capabilities.source && !capabilities.outpaint && !capabilities.rgba) return null

  const source = String(params.image_guide || '')
  const mask = String(params.image_mask || '')
  const chips = [
    capabilities.twoK ? t('imageEdit.native2k') : null,
    capabilities.refs && capabilities.maxRefs != null
      ? t('imageEdit.refs', { count: capabilities.maxRefs })
      : null,
    capabilities.inpaint ? t('imageEdit.mask') : null,
    capabilities.outpaint ? t('imageEdit.outpaint') : null,
    capabilities.rgba ? t('imageEdit.rgba') : null,
  ].filter((item): item is string => Boolean(item))

  return (
    <section className="space-y-2" aria-label={t('imageEdit.title')}>
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">
        {t('imageEdit.title')}
      </label>
      <div className="flex flex-wrap gap-1">
        {chips.map(chip => (
          <span key={chip} className="rounded-full border border-border bg-bg-tertiary px-2 py-0.5 text-[10px] text-text-secondary">
            {chip}
          </span>
        ))}
      </div>
      {capabilities.rgba && (
        <p className="text-[10px] text-text-muted">{t('imageEdit.rgbaHint')}</p>
      )}
      {capabilities.source && !batch && (
        <>
          <WangpMediaInput
            label={t('imageEdit.source')}
            kind="image"
            path={source}
            keepLocal
            onChoose={item => setStudioImageSource(item?.url || item?.name)}
          />
          {source && capabilities.inpaint ? (
            <WangpMediaInput
              label={t('imageEdit.maskImage')}
              kind="image"
              path={mask}
              keepLocal
              onChoose={item => setStudioImageMask(item?.url || item?.name)}
            />
          ) : (
            <p className="text-[10px] text-text-muted">{t('imageEdit.sourceHint')}</p>
          )}
        </>
      )}
      {capabilities.outpaint && source && !batch ? (
        <label className="block text-[11px] text-text-secondary">
          {t('imageEdit.outpaintMargins')}
          <input
            className="mt-1 w-full rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary"
            placeholder="0 0 0 0"
            value={String(params.video_guide_outpainting || '')}
            onChange={event => setParam('video_guide_outpainting', event.target.value.trim() || undefined)}
          />
          <span className="mt-1 block text-[10px] text-text-muted">{t('imageEdit.outpaintHint')}</span>
        </label>
      ) : null}
      {mask ? (
        <label className="block text-[11px] text-text-secondary">
          {t('imageEdit.denoising')}
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            className="mt-1 w-full"
            value={Number(params.denoising_strength ?? 1)}
            onChange={event => setParam('denoising_strength', Number(event.target.value))}
          />
        </label>
      ) : null}
      <ImageEditControls />
    </section>
  )
}
