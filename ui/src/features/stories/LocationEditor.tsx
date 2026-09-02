import { ChevronDown, ChevronUp, ImagePlus, Loader2, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, Field } from './storyLabChrome'
import { moveItem, pruneUnusedAssets } from './storyLabEditors'
import { useStoryLabVisuals } from './storyLabVisuals'
import { ReferenceGallery } from './ReferenceGallery'
import type { StoryLocation, StoryProject } from './types'

export function LocationEditor({
  location, index, total, project, update,
}: {
  location: StoryLocation
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  const set = (patch: Partial<StoryLocation>) => update(current => {
    current.world.locations = current.world.locations.map(item => item.id === location.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} space-y-3`}>
      <div className="flex justify-between gap-2">
        <h4 className="text-sm font-semibold text-text-primary">{location.name}</h4>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title={t('location.moveUp')} onClick={() => update(current => {
            moveItem(current.world.locations, index, index - 1)
            return current
          })}><ChevronUp size={13} /></button>
          <button className={button} disabled={index === total - 1} title={t('location.moveDown')} onClick={() => update(current => {
            moveItem(current.world.locations, index, index + 1)
            return current
          })}><ChevronDown size={13} /></button>
          <button className="text-red-400 p-1" onClick={() => update(current => {
            current.world.locations = current.world.locations.filter(item => item.id !== location.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        <Field label={t('location.name')} value={location.name} onChange={name => set({ name })} />
        <Field label={t('location.purpose')} value={location.purpose} onChange={purpose => set({ purpose })} />
        <Field label={t('location.description')} value={location.description} onChange={description => set({ description })} rows={4} />
        <Field label={t('location.conceptPrompt')} value={location.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} />
        <Field label={t('location.negativePrompt')} value={location.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={3} />
      </div>
      <div className="flex gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !location.visualPrompt.trim()} onClick={() => void generateVisual({ kind: 'location', id: location.id }, location.visualPrompt)}>
          {imageBusy === `location:${location.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {location.referenceAssetIds.length ? t('location.generateAnother') : t('location.generate')}
        </button>
        <button className={button} onClick={() => requestUpload({ kind: 'location', id: location.id })}><Upload size={13} /> {t('location.addReference')}</button>
      </div>
      <ReferenceGallery ids={location.referenceAssetIds} assets={project.assets} onRemove={id => removeReference('location', location.id, id)} />
    </div>
  )
}
