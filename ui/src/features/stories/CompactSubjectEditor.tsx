import { Check, ChevronDown, ChevronUp, ImagePlus, Loader2, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { moveItem, pruneUnusedAssets } from './storyLabEditors'
import { button, Field } from './storyLabChrome'
import { ReferenceGallery } from './ReferenceGallery'
import { useStoryLabVisuals } from './storyLabVisuals'
import type { StoryCharacter, StoryProject } from './types'

export function CompactSubjectEditor({
  character, index, total, project, update, requiresVisualIdentity,
}: {
  character: StoryCharacter
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  requiresVisualIdentity: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  const set = (change: Partial<StoryCharacter>) => update(current => {
    current.characters = current.characters.map(item => item.id === character.id
      ? { ...item, approval: 'draft', ...change } : item)
    return current
  })
  const primaryAsset = character.primaryReferenceAssetId
    ? project.assets[character.primaryReferenceAssetId]
    : undefined
  const hasPrimary = primaryAsset?.approval === 'approved'
  const canApprove = !requiresVisualIdentity || hasPrimary
  return (
    <div id={`story-review-character-${character.id}`} className="scroll-mt-4 rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-text-primary">{character.name || t('compact.unnamed')}</p>
          <p className={`text-[9px] ${hasPrimary || !requiresVisualIdentity ? 'text-emerald-300' : 'text-amber-300'}`}>
            {requiresVisualIdentity
              ? hasPrimary ? t('compact.identityApproved') : t('compact.identityMissing')
              : t('compact.directVideoEnough')}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title={t('compact.moveUp')} onClick={() => update(current => { moveItem(current.characters, index, index - 1); return current })}><ChevronUp size={12} /></button>
          <button className={button} disabled={index === total - 1} title={t('compact.moveDown')} onClick={() => update(current => { moveItem(current.characters, index, index + 1); return current })}><ChevronDown size={12} /></button>
          <button className="p-1 text-red-400" title={t('compact.remove')} onClick={() => update(current => {
            current.characters = current.characters.filter(item => item.id !== character.id)
            current.relationships = current.relationships.filter(item => item.fromCharacterId !== character.id && item.toCharacterId !== character.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={13} /></button>
        </div>
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        <Field label={t('compact.name')} value={character.name} onChange={name => set({ name })} />
        <Field label={t('compact.onCameraRole')} value={character.role} onChange={role => set({ role })} />
        <Field label={t('compact.recognizableLook')} value={character.appearance} onChange={appearance => set({ appearance })} rows={3} />
        <Field label={t('compact.wardrobe')} value={character.wardrobe} onChange={wardrobe => set({ wardrobe })} rows={3} />
        <div className="sm:col-span-2"><Field label={t('compact.identityPrompt')} value={character.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} /></div>
      </div>
      <details className="rounded border border-border px-2 py-1.5 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">{t('compact.optionalVoice')}</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <Field label={t('compact.voice')} value={character.voice} onChange={voice => set({ voice })} rows={2} />
          <Field label={t('compact.visibleMotivation')} value={character.desire} onChange={desire => set({ desire })} rows={2} />
          <div className="sm:col-span-2"><Field label={t('compact.negativePrompt')} value={character.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={2} /></div>
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !character.visualPrompt.trim()}
          onClick={() => void generateVisual({ kind: 'character', id: character.id }, character.visualPrompt)}>
          {imageBusy === `character:${character.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {hasPrimary ? t('compact.createVariation') : t('compact.createIdentity')}
        </button>
        <button className={button} onClick={() => requestUpload({ kind: 'character', id: character.id })}><Upload size={13} /> {t('compact.uploadImages')}</button>
        <button className={`${button} ${character.approval === 'approved' ? 'border-emerald-500 text-emerald-400' : ''}`}
          disabled={!canApprove}
          title={requiresVisualIdentity
            ? hasPrimary ? t('compact.approveIdentityTitle') : t('compact.needPrimaryTitle')
            : t('compact.approveDescriptionTitle')}
          onClick={() => set({ approval: character.approval === 'approved' ? 'draft' : 'approved' })}>
          <Check size={13} /> {requiresVisualIdentity
            ? character.approval === 'approved' ? t('compact.identityApprovedBtn') : t('compact.approveIdentity')
            : character.approval === 'approved' ? t('compact.descriptionApproved') : t('compact.approveDescription')}
        </button>
      </div>
      <ReferenceGallery ids={character.referenceAssetIds} assets={project.assets} primaryId={character.primaryReferenceAssetId}
        onPrimary={primaryReferenceAssetId => set({ primaryReferenceAssetId })} onRemove={id => removeReference('character', character.id, id)} />
    </div>
  )
}
