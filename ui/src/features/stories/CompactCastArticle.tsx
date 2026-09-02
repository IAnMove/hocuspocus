import { Check, ImagePlus, Loader2, Plus, Sparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { emptyCharacter } from './storyLabEditors'
import { button, requiredPreparationButton, type StoryGenerationOptions } from './storyLabChrome'
import { CompactPrepStatus } from './CompactPrepStatus'
import { CompactSubjectEditor } from './CompactSubjectEditor'
import { useStoryLabVisuals } from './storyLabVisuals'
import type { StoryGenerationScope, StoryProject } from './types'

export function CompactCastArticle({
  project, update, busy, generateSection, approveSection, isSectionApproved, castReady,
  requiresVisualIdentities, isMusicVideo, isTrailer,
}: {
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  generateSection: (scope: StoryGenerationScope, options?: StoryGenerationOptions) => void
  approveSection: (scope: keyof StoryProject['approvals']) => void
  isSectionApproved: (scope: keyof StoryProject['approvals']) => boolean
  castReady: boolean
  requiresVisualIdentities: boolean
  isMusicVideo: boolean
  isTrailer: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const { imageBusy, referenceBatchBusy } = useStoryLabVisuals()
  return (
    <article id="story-review-characters" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">2 · {isMusicVideo ? t('compact.subjectsMusic') : isTrailer ? t('compact.subjectsTrailer') : t('compact.subjectsQuick')}</h4>
          <p className="text-[9px] text-text-muted">{t('compact.subjectsHint')}</p>
        </div>
        <CompactPrepStatus ready={castReady} approved={isSectionApproved('characters')} />
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
  )
}
