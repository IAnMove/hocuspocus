import { Check, ChevronDown, ChevronUp, Film, ImagePlus, Loader2, Music, Plus, Sparkles, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { emptyCharacter, moveItem, pruneUnusedAssets } from './storyLabEditors'
import { button, input, panel, requiredPreparationButton, Field, type StoryGenerationOptions, type StoryLabTab } from './storyLabChrome'
import { storyId } from './model'
import { LocationEditor } from './LocationEditor'
import { ReferenceGallery } from './ReferenceGallery'
import { useStoryLabVisuals } from './storyLabVisuals'
import type { StoryBeat, StoryCharacter, StoryGenerationScope, StoryProject } from './types'

export function CompactVideoWorkspace({
  project, update, busy, generateSection, approveSection, isSectionApproved, navigate, requiresVisualIdentities,
}: {
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  generateSection: (scope: StoryGenerationScope, options?: StoryGenerationOptions) => void
  approveSection: (scope: keyof StoryProject['approvals']) => void
  isSectionApproved: (scope: keyof StoryProject['approvals']) => boolean
  navigate: (tab: StoryLabTab) => void
  requiresVisualIdentities: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, referenceBatchBusy, generateVisual, requestUpload, removeReference } = useStoryLabVisuals()
  const isMusicVideo = project.projectType === 'music_video'
  const isTrailer = project.projectType === 'trailer'
  const worldReady = Boolean(project.world.summary.trim() && project.world.visualLanguage.trim())
  const castReady = project.characters.length > 0 && project.characters.every(character =>
    character.approval === 'approved'
    && (!requiresVisualIdentities
      || Boolean(character.primaryReferenceAssetId
        && project.assets[character.primaryReferenceAssetId]?.approval === 'approved')))
  const sequenceReady = project.beats.length >= 3 && project.beats.every(beat =>
    Boolean(beat.summary.trim() && beat.conflict.trim() && beat.turn.trim()))
  const status = (ready: boolean, approved: boolean) => (
    <span className={`rounded-full border px-2 py-1 text-[9px] ${ready
      ? approved ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      : 'border-border bg-bg-tertiary text-text-muted'}`}>
      {ready ? approved ? t('status.approved') : t('compact.readyToApprove') : t('compact.pending')}
    </span>
  )

  return (
    <section className={`${panel} mt-4 ${isMusicVideo ? 'border-pink-500/25' : 'border-cyan-500/25'}`}>
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className={`text-[9px] font-semibold uppercase tracking-[0.18em] ${isMusicVideo ? 'text-pink-300' : 'text-cyan-300'}`}>
            {t('compact.prepTable')}
          </p>
          <h3 className="mt-1 text-base font-semibold text-text-primary">
            {isMusicVideo ? t('compact.musicTitle') : isTrailer ? t('compact.trailerTitle') : t('compact.quickTitle')}
          </h3>
          <p className="mt-1 max-w-3xl text-xs text-text-muted">
            {isMusicVideo ? t('compact.musicDescription') : isTrailer ? t('compact.trailerDescription') : t('compact.quickDescription')}
          </p>
          <p className="mt-2 rounded-md border border-accent-blue/20 bg-accent-blue/5 px-2.5 py-1.5 text-[9px] leading-relaxed text-text-muted">
            <span className="font-medium text-accent-blue">{t('compact.llmHintLead')}</span> {t('compact.llmHint')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={button} onClick={() => navigate('assets')}><ImagePlus size={13} /> {t('compact.importImages')}</button>
          {isMusicVideo && <button className={button} onClick={() => navigate('music')}><Music size={13} /> {t('compact.editSong')}</button>}
          <button className={`${button} border-accent-blue/60 text-accent-blue`} onClick={() => navigate(isTrailer ? 'trailer' : 'productions')}><Film size={13} /> {isTrailer ? t('compact.createTrailer') : t('compact.goGenerate')}</button>
        </div>
      </div>

      <div className="space-y-4">
        <article id="story-review-world" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">{t('compact.worldStep')}</h4>
              <p className="text-[9px] text-text-muted">{t('compact.worldHint')}</p>
            </div>
            {status(worldReady, isSectionApproved('world'))}
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

        <article id="story-review-characters" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">2 · {isMusicVideo ? t('compact.subjectsMusic') : isTrailer ? t('compact.subjectsTrailer') : t('compact.subjectsQuick')}</h4>
              <p className="text-[9px] text-text-muted">{t('compact.subjectsHint')}</p>
            </div>
            {status(castReady, isSectionApproved('characters'))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={`${button} ${!castReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('characters')}
              title={t('compact.prepareSubjectsTextTitle')}>
              {busy === 'characters' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('compact.prepareSubjectsText')}
            </button>
            <button className={`${button} ${!castReady ? requiredPreparationButton : ''}`}
              disabled={Boolean(busy || imageBusy || referenceBatchBusy)}
              onClick={() => generateSection('characters', { generateImages: true })}
              title={t('compact.prepareSubjectsImagesTitle')}>
              {busy === 'characters' || referenceBatchBusy
                ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
              {t('compact.prepareSubjectsImages')}
            </button>
            <button className={button} onClick={() => update(current => { current.characters.push(emptyCharacter(t('characters.newName'))); return current })}>
              <Plus size={13} /> {t('compact.add')}
            </button>
            <button className={`${button} ${isSectionApproved('characters') ? 'border-emerald-500 text-emerald-400' : ''}`}
              onClick={() => approveSection('characters')}><Check size={13} /> {isSectionApproved('characters') ? t('compact.approvedPlural') : t('compact.approveSet')}</button>
          </div>
          <p className="rounded-md border border-violet-500/25 bg-violet-500/5 px-2.5 py-1.5 text-[9px] leading-relaxed text-text-muted">
            {isTrailer ? t('compact.subjectsTrailerHint') : t('compact.subjectsMusicHint')}
          </p>
          <div className="space-y-3">
            {project.characters.map((character, index) => (
              <CompactSubjectEditor key={character.id} character={character} index={index} total={project.characters.length}
                project={project} update={update} requiresVisualIdentity={requiresVisualIdentities} />
            ))}
            {!project.characters.length && <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-text-muted">{t('compact.emptySubjects')}</p>}
          </div>
        </article>

        <article id="story-review-structure" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">3 · {isMusicVideo ? t('compact.sequenceMusic') : isTrailer ? t('compact.sequenceTrailer') : t('compact.sequenceQuick')}</h4>
              <p className="text-[9px] text-text-muted">{isMusicVideo ? t('compact.sequenceHintMusic') : isTrailer ? t('compact.sequenceHintTrailer') : t('compact.sequenceHintQuick')}</p>
            </div>
            {status(sequenceReady, isSectionApproved('structure'))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={`${button} ${!sequenceReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('structure')}
              title={t('compact.prepareSequenceTitle')}>
              {busy === 'structure' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('compact.prepareSequence')}
            </button>
            <button className={button} onClick={() => update(current => {
              current.beats.push({ id: storyId('beat'), stage: '', title: t('compact.newMoment'), summary: '', goal: '', conflict: '', turn: '' })
              return current
            })}><Plus size={13} /> {t('compact.addMoment')}</button>
            <button className={`${button} ${isSectionApproved('structure') ? 'border-emerald-500 text-emerald-400' : ''}`}
              onClick={() => approveSection('structure')}><Check size={13} /> {isSectionApproved('structure') ? t('compact.approvedFeminine') : t('compact.approveSequence')}</button>
          </div>
          <div className="space-y-2">
            {project.beats.map((beat, index) => (
              <CompactBeatEditor key={beat.id} beat={beat} index={index} total={project.beats.length} update={update} />
            ))}
            {!project.beats.length && <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-text-muted">{t('compact.emptyBeats')}</p>}
          </div>
        </article>
      </div>
    </section>
  )
}

function CompactSubjectEditor({
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

function CompactBeatEditor({ beat, index, total, update }: {
  beat: StoryBeat
  index: number
  total: number
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const set = (change: Partial<StoryBeat>) => update(current => {
    current.beats = current.beats.map(item => item.id === beat.id ? { ...item, ...change } : item)
    return current
  })
  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2">
      <div className="flex items-center gap-2">
        <span className="w-5 shrink-0 text-sm font-bold text-text-muted/60">{index + 1}</span>
        <input className={input} value={beat.title} onChange={event => set({ title: event.target.value })} placeholder={t('compact.momentName')} aria-label={t('compact.momentAria', { index: index + 1 })} />
        <button className={button} disabled={index === 0} title={t('compact.moveUp')} onClick={() => update(current => { moveItem(current.beats, index, index - 1); return current })}><ChevronUp size={12} /></button>
        <button className={button} disabled={index === total - 1} title={t('compact.moveDown')} onClick={() => update(current => { moveItem(current.beats, index, index + 1); return current })}><ChevronDown size={12} /></button>
        <button className="p-1 text-red-400" title={t('compact.remove')} onClick={() => update(current => { current.beats = current.beats.filter(item => item.id !== beat.id); return current })}><Trash2 size={12} /></button>
      </div>
      <Field label={t('compact.whatWeSee')} value={beat.summary} onChange={summary => set({ summary })} rows={3} />
      <div className="grid sm:grid-cols-2 gap-2">
        <Field label={t('compact.tension')} value={beat.conflict} onChange={conflict => set({ conflict })} rows={2} />
        <Field label={t('compact.nextCutChange')} value={beat.turn} onChange={turn => set({ turn })} rows={2} />
      </div>
      <details className="rounded border border-border px-2 py-1.5 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">{t('compact.optionalSection')}</summary>
        <div className="mt-2 grid sm:grid-cols-2 gap-2">
          <Field label={t('compact.sectionOrPhase')} value={beat.stage} onChange={stage => set({ stage })} />
          <Field label={t('compact.momentGoal')} value={beat.goal} onChange={goal => set({ goal })} rows={2} />
        </div>
      </details>
    </div>
  )
}
