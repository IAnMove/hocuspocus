import { Check, ImagePlus, Loader2, Plus, Sparkles, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, requiredPreparationButton, Field, type StoryGenerationOptions } from './storyLabChrome'
import { storyId } from './model'
import { LocationEditor } from './LocationEditor'
import { ReferenceGallery } from './ReferenceGallery'
import { useStoryLabVisuals } from './storyLabVisuals'
import { CompactPrepStatus } from './CompactPrepStatus'
import type { StoryGenerationScope, StoryProject } from './types'

export function CompactWorldArticle({
  project, update, busy, generateSection, approveSection, isSectionApproved, worldReady, isMusicVideo, isTrailer,
}: {
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  generateSection: (scope: StoryGenerationScope, options?: StoryGenerationOptions) => void
  approveSection: (scope: keyof StoryProject['approvals']) => void
  isSectionApproved: (scope: keyof StoryProject['approvals']) => boolean
  worldReady: boolean
  isMusicVideo: boolean
  isTrailer: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, referenceBatchBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  return (
    <article id="story-review-world" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">{t('compact.worldStep')}</h4>
          <p className="text-[9px] text-text-muted">{t('compact.worldHint')}</p>
        </div>
        <CompactPrepStatus ready={worldReady} approved={isSectionApproved('world')} />
      </div>
      <Field label={isMusicVideo ? t('compact.worldFieldMusic') : isTrailer ? t('compact.worldFieldTrailer') : t('compact.worldFieldQuick')} value={project.world.summary}
        onChange={summary => update(current => { current.world.summary = summary; return current })} rows={3} />
      <Field label={t('compact.lighting')} value={project.world.visualLanguage}
        onChange={visualLanguage => update(current => { current.world.visualLanguage = visualLanguage; return current })} rows={3} />
      <Field label={t('compact.baseImagePrompt')} value={project.world.visualPrompt}
        onChange={visualPrompt => update(current => { current.world.visualPrompt = visualPrompt; return current })} rows={4} />
      <details className="rounded-md border border-border bg-bg-tertiary/35 p-2 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">{t('compact.avoidImages')}</summary>
        <div className="mt-3 space-y-3">
          <Field label={t('compact.negativePrompt')} value={project.world.negativePrompt}
            onChange={negativePrompt => update(current => { current.world.negativePrompt = negativePrompt; return current })} rows={3} />
          <div className="flex items-center justify-between gap-2">
            <span>{t('compact.extraLocations', { count: project.world.locations.length })}</span>
            <button className={button} onClick={() => update(current => {
              current.world.locations.push({ id: storyId('location'), name: t('world.newLocationName'), purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [] })
              return current
            })}><Plus size={12} /> {t('compact.add')}</button>
          </div>
          {project.world.locations.map((location, index) => (
            <LocationEditor key={location.id} location={location} index={index} total={project.world.locations.length}
              project={project} update={update} />
          ))}
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <button className={`${button} ${!worldReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('world')}
          title={t('compact.prepareWorldTextTitle')}>
          {busy === 'world' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('compact.prepareWorldText')}
        </button>
        <button className={button} disabled={Boolean(imageBusy) || referenceBatchBusy || !project.world.visualPrompt.trim()}
          onClick={() => void generateVisual({ kind: 'world' }, project.world.visualPrompt)}>
          {imageBusy === 'world:world' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {t('compact.generateImage')}
        </button>
        <button className={button} onClick={() => requestUpload({ kind: 'world' })}><Upload size={13} /> {t('compact.addReference')}</button>
        <button className={`${button} ${isSectionApproved('world') ? 'border-emerald-500 text-emerald-400' : ''}`}
          onClick={() => approveSection('world')}><Check size={13} /> {isSectionApproved('world') ? t('chrome.approved') : t('chrome.approve')}</button>
      </div>
      <ReferenceGallery ids={project.world.referenceAssetIds} assets={project.assets}
        onRemove={id => removeReference('world', undefined, id)} />
    </article>
  )
}
