import { Check, ChevronDown, ChevronUp, ImagePlus, Loader2, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, Field } from './storyLabChrome'
import { moveItem, pruneUnusedAssets } from './storyLabEditors'
import { useStoryLabVisuals } from './storyLabVisuals'
import { ReferenceGallery } from './ReferenceGallery'
import type { StoryCharacter, StoryProject } from './types'

export function CharacterEditor({
  character, index, total, project, update,
}: {
  character: StoryCharacter
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  const set = (patch: Partial<StoryCharacter>) => update(current => {
    current.characters = current.characters.map(item => item.id === character.id ? { ...item, approval: 'draft', ...patch } : item)
    return current
  })
  return (
    <div id={`story-review-character-${character.id}`} className={`${panel} scroll-mt-4 space-y-3`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary">{character.name}</h3>
          <button className={`${button} ${character.approval === 'approved' ? 'border-emerald-500 text-emerald-400' : ''}`} onClick={() => set({ approval: character.approval === 'approved' ? 'draft' : 'approved' })}>
            <Check size={12} /> {character.approval === 'approved' ? t('status.approved') : t('status.draft')}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title={t('characters.moveUp')} onClick={() => update(current => {
            moveItem(current.characters, index, index - 1)
            return current
          })}><ChevronUp size={13} /></button>
          <button className={button} disabled={index === total - 1} title={t('characters.moveDown')} onClick={() => update(current => {
            moveItem(current.characters, index, index + 1)
            return current
          })}><ChevronDown size={13} /></button>
          <button className="text-red-400 p-1" onClick={() => update(current => {
            current.characters = current.characters.filter(item => item.id !== character.id)
            current.relationships = current.relationships.filter(item => item.fromCharacterId !== character.id && item.toCharacterId !== character.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="grid md:grid-cols-3 gap-3">
        <Field label={t('characters.fields.name')} value={character.name} onChange={name => set({ name })} />
        <Field label={t('characters.fields.role')} value={character.role} onChange={role => set({ role })} />
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('characters.fields.age')} value={character.age} onChange={age => set({ age })} />
          <Field label={t('characters.fields.pronouns')} value={character.pronouns} onChange={pronouns => set({ pronouns })} />
        </div>
        <Field label={t('characters.fields.personality')} value={character.personality} onChange={personality => set({ personality })} rows={3} />
        <Field label={t('characters.fields.desire')} value={character.desire} onChange={desire => set({ desire })} rows={3} />
        <Field label={t('characters.fields.need')} value={character.need} onChange={need => set({ need })} rows={3} />
        <Field label={t('characters.fields.flaw')} value={character.flaw} onChange={flaw => set({ flaw })} rows={3} />
        <Field label={t('characters.fields.conflict')} value={character.conflict} onChange={conflict => set({ conflict })} rows={3} />
        <Field label={t('characters.fields.arc')} value={character.arc} onChange={arc => set({ arc })} rows={3} />
        <Field label={t('characters.fields.voice')} value={character.voice} onChange={voice => set({ voice })} rows={3} />
        <Field label={t('characters.fields.appearance')} value={character.appearance} onChange={appearance => set({ appearance })} rows={3} />
        <Field label={t('characters.fields.wardrobe')} value={character.wardrobe} onChange={wardrobe => set({ wardrobe })} rows={3} />
        <Field label={t('characters.fields.visualPrompt')} value={character.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} />
        <Field label={t('characters.fields.negativePrompt')} value={character.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={4} />
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !character.visualPrompt.trim()} onClick={() => void generateVisual({ kind: 'character', id: character.id }, character.visualPrompt)}>
          {imageBusy === `character:${character.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {character.primaryReferenceAssetId ? t('characters.generateVariation') : t('characters.generateFirst')}
        </button>
        <button className={button} onClick={() => requestUpload({ kind: 'character', id: character.id })}><Upload size={13} /> {t('characters.upload')}</button>
      </div>
      <ReferenceGallery ids={character.referenceAssetIds} assets={project.assets} primaryId={character.primaryReferenceAssetId} onPrimary={id => set({ primaryReferenceAssetId: id })} onRemove={id => removeReference('character', character.id, id)} />
    </div>
  )
}
