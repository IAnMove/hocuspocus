import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { AspectRatioGrid } from './AspectRatioGrid'
import { ImageEditSection } from './ImageEditSection'
import { ImageFitDialog } from './ImageFitDialog'
import { ImageIntentChooser, ImageIntentSwitch } from './ImageIntentChooser'
import { ImageRefSection } from './ImageRefSection'
import { OutputCount } from './OutputCount'
import { ImageBatchControls } from './ImageBatchControls'
import { PanoramaLoopPanel } from './PanoramaLoopPanel'
import { PromptInput } from './PromptInput'
import { ResolutionPresets } from './ResolutionPresets'
import { supportsImageIntent } from '../../features/studio/imageStudioIntent'

export function ImageStudioPanel() {
  const { t } = useUiTranslation('studio')
  const intent = useStore(s => s.imageStudioIntent)
  const options = useStore(s => s.modelOptions)
  const source = String(useStore(s => s.params.image_guide) || '')
  const resolution = String(useStore(s => s.params.resolution) || '')
  const queueCount = useStore(s => s.jobs.filter(job => ['queued', 'waiting_resource', 'running'].includes(job.status)).length)
  const [fitOpen, setFitOpen] = useState(false)
  const batch = useStore(s => Boolean(s.imageBatch?.perLine || (s.imageStudioIntent === 'edit' && s.imageBatch?.enabled)))
  const manySources = useStore(s => s.imageBatch?.enabled && s.imageStudioIntent === 'edit')

  if (intent === 'chooser') return <ImageIntentChooser />
  if (!supportsImageIntent(intent, options)) return <><ImageIntentSwitch /><p role="status" className="text-xs text-text-muted">{t('imageIntent.incompatible')}</p></>

  return (
    <div className="space-y-3">
      <ImageIntentSwitch />
      <PromptInput />
      {(intent === 'new' || intent === 'edit' || intent === 'character') && <ImageBatchControls />}
      {intent === 'edit' && <ImageEditSection />}
      {intent === 'edit' && !manySources && source ? (
        <button
          type="button"
          onClick={() => setFitOpen(true)}
          className="w-full rounded-lg border border-border px-2 py-1.5 text-[11px] text-text-secondary hover:text-text-primary"
        >
          {t('imageFit.open')}
        </button>
      ) : null}
      {(intent === 'character' || (intent === 'edit' && options?.image_ref_inpaint)) && <ImageRefSection />}
      {intent === 'loop' && <PanoramaLoopPanel />}
      {intent !== 'loop' && (
        <>
          <ResolutionPresets />
          <AspectRatioGrid />
          {resolution ? <p className="text-[10px] text-text-muted">{t('imageIntent.canvas', { size: resolution })}</p> : null}
          {!batch && <OutputCount />}
        </>
      )}
      {queueCount > 0 ? (
        <p className="text-[10px] text-text-muted">{t('generate.activeCount', { count: queueCount })}</p>
      ) : null}
      {fitOpen && intent === 'edit' && !manySources && source ? <ImageFitDialog key={source} source={source} onClose={() => setFitOpen(false)} /> : null}
    </div>
  )
}
