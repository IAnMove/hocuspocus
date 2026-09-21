import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { AspectRatioGrid } from './AspectRatioGrid'
import { ImageEditSection } from './ImageEditSection'
import { ImageFitDialog } from './ImageFitDialog'
import { ImageIntentChooser, ImageIntentSwitch } from './ImageIntentChooser'
import { ImageRefSection } from './ImageRefSection'
import { OutputCount } from './OutputCount'
import { PanoramaLoopPanel } from './PanoramaLoopPanel'
import { PromptInput } from './PromptInput'
import { ResolutionPresets } from './ResolutionPresets'

export function ImageStudioPanel() {
  const { t } = useUiTranslation('studio')
  const intent = useStore(s => s.imageStudioIntent)
  const source = String(useStore(s => s.params.image_guide) || '')
  const resolution = String(useStore(s => s.params.resolution) || '')
  const queueCount = useStore(s => s.jobs.filter(job => ['queued', 'waiting_resource', 'running'].includes(job.status)).length)
  const [fitOpen, setFitOpen] = useState(false)

  if (intent === 'chooser') return <ImageIntentChooser />

  return (
    <div className="space-y-3">
      <ImageIntentSwitch />
      <PromptInput />
      {intent === 'edit' && <ImageEditSection />}
      {intent === 'edit' && source ? (
        <button
          type="button"
          onClick={() => setFitOpen(true)}
          className="w-full rounded-lg border border-border px-2 py-1.5 text-[11px] text-text-secondary hover:text-text-primary"
        >
          {t('imageFit.open')}
        </button>
      ) : null}
      {intent === 'character' && <ImageRefSection />}
      {intent === 'loop' && <PanoramaLoopPanel />}
      {intent !== 'loop' && (
        <>
          <ResolutionPresets />
          <AspectRatioGrid />
          {resolution ? <p className="text-[10px] text-text-muted">{t('imageIntent.canvas', { size: resolution })}</p> : null}
          <OutputCount />
        </>
      )}
      {queueCount > 0 ? (
        <p className="text-[10px] text-text-muted">{t('generate.activeCount', { count: queueCount })}</p>
      ) : null}
      {fitOpen && intent === 'edit' && source ? <ImageFitDialog key={source} source={source} onClose={() => setFitOpen(false)} /> : null}
    </div>
  )
}
