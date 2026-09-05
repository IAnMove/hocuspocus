import { ImagePlus, Loader2, Plus, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, Field, SectionHeader, type StoryLabSectionTabProps } from './storyLabChrome'
import { storyId } from './model'
import { LocationEditor } from './LocationEditor'
import { ReferenceGallery } from './ReferenceGallery'
import { useStoryLabVisuals } from './storyLabVisuals'

const WORLD_FIELDS = [
  ['period', 'world.period'],
  ['geography', 'world.geography'],
  ['society', 'world.society'],
  ['technology', 'world.technology'],
] as const

export function StoryWorldTab({
  project,
  patch,
  update,
  busy,
  instruction,
  setInstruction,
  generate,
  approve,
  isApproved,
}: StoryLabSectionTabProps & {
  patch: (patch: Partial<typeof project>) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, referenceBatchBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  return (
    <>
      <div id="story-review-world" className="scroll-mt-4">
        <SectionHeader title={t('world.title')} description={t('world.description')} scope="world" busy={busy} approved={isApproved('world')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('world')} />
      </div>
      <div className={`${panel} grid md:grid-cols-2 gap-3`}>
        <div className="md:col-span-2"><Field label={t('world.summary')} value={project.world.summary} onChange={summary => patch({ world: { ...project.world, summary } })} rows={5} /></div>
        {WORLD_FIELDS.map(([key, labelKey]) => (
          <Field key={key} label={t(labelKey)} value={project.world[key]} onChange={value => patch({ world: { ...project.world, [key]: value } })} rows={2} />
        ))}
        <div className="md:col-span-2"><Field label={t('world.rules')} value={project.world.rules.join('\n')} onChange={value => patch({ world: { ...project.world, rules: value.split('\n').filter(Boolean) } })} rows={4} /></div>
        <div className="md:col-span-2"><Field label={t('world.visualLanguage')} value={project.world.visualLanguage} onChange={visualLanguage => patch({ world: { ...project.world, visualLanguage } })} rows={3} /></div>
        <Field label={t('world.visualPrompt')} value={project.world.visualPrompt} onChange={visualPrompt => patch({ world: { ...project.world, visualPrompt } })} rows={4} />
        <Field label={t('world.negativePrompt')} value={project.world.negativePrompt} onChange={negativePrompt => patch({ world: { ...project.world, negativePrompt } })} rows={4} />
        <div className="md:col-span-2 flex gap-2">
          <button className={button} disabled={Boolean(imageBusy) || referenceBatchBusy || !project.world.visualPrompt.trim()} onClick={() => void generateVisual({ kind: 'world' }, project.world.visualPrompt)}>
            {imageBusy === 'world:world' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {project.world.referenceAssetIds.length ? t('world.generateAnotherConcept') : t('world.generateConcept')}
          </button>
          <button className={button} onClick={() => requestUpload({ kind: 'world' })}><Upload size={13} /> {t('world.addReference')}</button>
        </div>
        <div className="md:col-span-2"><ReferenceGallery ids={project.world.referenceAssetIds} assets={project.assets} onRemove={id => removeReference('world', undefined, id)} /></div>
      </div>
      <div className="mt-4 space-y-3">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-semibold text-text-primary">{t('world.locations')}</h3>
          <button className={button} onClick={() => update(current => {
            current.world.locations.push({ id: storyId('location'), name: t('world.newLocationName'), purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [] })
            return current
          })}><Plus size={13} /> {t('world.addLocation')}</button>
        </div>
        {project.world.locations.map((location, index) => (
          <LocationEditor key={location.id} location={location} index={index} total={project.world.locations.length} project={project} update={update} />
        ))}
      </div>
    </>
  )
}
