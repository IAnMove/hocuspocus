import { useUiTranslation } from '../../i18n'
import { snapImageResolution } from '../../lib/imageResolution'
import { forgetLocalImage, localEditPreview } from '../../lib/localEditImages'
import { mergeVideoPromptLetters, studioImageEditCapabilities } from '../../lib/studioImageEdit'
import { useStore } from '../../stores/useStore'
import { WangpMediaInput } from './WangpMediaInput'

export function ImageEditSection() {
  const { t } = useUiTranslation('studio')
  const modelOptions = useStore(s => s.modelOptions)
  const params = useStore(s => s.params)
  const setParams = useStore(s => s.setParams)
  const setParam = useStore(s => s.setParam)
  const capabilities = studioImageEditCapabilities(modelOptions)
  if (!capabilities) return null
  if (!capabilities.inpaint && !capabilities.outpaint && !capabilities.rgba) return null

  const flags = String(params.video_prompt_type || '')
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
      {capabilities.inpaint && (
        <>
          <WangpMediaInput
            label={t('imageEdit.source')}
            kind="image"
            path={source}
            keepLocal
            onChoose={item => {
              if (!item) {
                forgetLocalImage(source)
                forgetLocalImage(mask)
                setParams({
                  image_guide: undefined,
                  image_mask: undefined,
                  video_prompt_type: mergeVideoPromptLetters(flags, '', 'VAG'),
                })
                return
              }
              const next = item.url || item.name
              setParams({
                image_guide: next,
                video_prompt_type: mergeVideoPromptLetters(flags, mask ? 'VAG' : 'V', ''),
              })
              const previewUrl = localEditPreview(next)
              if (previewUrl.startsWith('blob:') || previewUrl.startsWith('/api/') || previewUrl.startsWith('http')) {
                const preview = new Image()
                preview.onload = () => {
                  useStore.getState().setParam('resolution', snapImageResolution(preview.width, preview.height, 2048))
                }
                preview.src = previewUrl
              }
            }}
          />
          {source ? (
            <WangpMediaInput
              label={t('imageEdit.maskImage')}
              kind="image"
              path={mask}
              keepLocal
              onChoose={item => {
                if (!item) {
                  forgetLocalImage(mask)
                  setParams({
                    image_mask: undefined,
                    video_prompt_type: mergeVideoPromptLetters(flags, 'V', 'AG'),
                  })
                  return
                }
                setParams({
                  image_mask: item.url || item.name,
                  video_prompt_type: mergeVideoPromptLetters(flags, 'VAG', ''),
                })
              }}
            />
          ) : (
            <p className="text-[10px] text-text-muted">{t('imageEdit.sourceHint')}</p>
          )}
        </>
      )}
      {capabilities.outpaint && source ? (
        <label className="block text-[11px] text-text-secondary">
          {t('imageEdit.outpaintMargins')}
          <input
            className="mt-1 w-full rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary"
            placeholder="0 0 0 0"
            value={String(params.video_guide_outpainting || '')}
            onChange={event => setParam('video_guide_outpainting', event.target.value)}
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
    </section>
  )
}
