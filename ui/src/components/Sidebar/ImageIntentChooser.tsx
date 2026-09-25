import { useUiTranslation } from '../../i18n'
import { IMAGE_STUDIO_INTENTS, supportsImageIntent, type ImageStudioIntent } from '../../features/studio/imageStudioIntent'
import { useStore } from '../../stores/useStore'

export function ImageIntentChooser() {
  const { t } = useUiTranslation('studio')
  const setIntent = useStore(s => s.setImageStudioIntent)
  const options = useStore(s => s.modelOptions)
  return (
    <section className="space-y-2" aria-label={t('imageIntent.title')}>
      <p className="text-[11px] text-text-muted">{t('imageIntent.subtitle')}</p>
      <div className="grid grid-cols-2 gap-2">
        {IMAGE_STUDIO_INTENTS.filter(item => supportsImageIntent(item.id, options)).map(item => (
          <button
            key={item.id}
            type="button"
            onClick={() => setIntent(item.id)}
            className="rounded-xl border border-border bg-bg-tertiary/50 px-3 py-3 text-left hover:border-accent-blue hover:bg-bg-active"
          >
            <div className="text-base text-accent-blue">{item.icon}</div>
            <div className="mt-1 text-xs font-medium text-text-primary">{t(`imageIntent.${item.id}`)}</div>
            <div className="mt-0.5 text-[10px] leading-snug text-text-muted">{t(`imageIntent.${item.id}Hint`)}</div>
          </button>
        ))}
      </div>
    </section>
  )
}

export function ImageIntentSwitch() {
  const { t } = useUiTranslation('studio')
  const intent = useStore(s => s.imageStudioIntent)
  const setIntent = useStore(s => s.setImageStudioIntent)
  const reset = useStore(s => s.resetImageStudio)
  const options = useStore(s => s.modelOptions)
  if (intent === 'chooser') return null
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex flex-wrap gap-1">
        {IMAGE_STUDIO_INTENTS.filter(item => supportsImageIntent(item.id, options)).map(item => (
          <button
            key={item.id}
            type="button"
            onClick={() => setIntent(item.id as ImageStudioIntent)}
            className={`rounded-full border px-2 py-0.5 text-[10px] ${
              intent === item.id
                ? 'border-accent-blue bg-accent-blue/15 text-text-primary'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
          >
            {t(`imageIntent.${item.id}`)}
          </button>
        ))}
      </div>
      <button type="button" onClick={reset} className="shrink-0 text-[10px] text-accent-blue hover:underline">
        {t('imageIntent.startOver')}
      </button>
    </div>
  )
}
