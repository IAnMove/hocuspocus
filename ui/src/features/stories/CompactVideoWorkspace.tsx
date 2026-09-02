import { Film, ImagePlus, Music } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, type StoryGenerationOptions, type StoryLabTab } from './storyLabChrome'
import { CompactCastArticle } from './CompactCastArticle'
import { CompactSequenceArticle } from './CompactSequenceArticle'
import { CompactWorldArticle } from './CompactWorldArticle'
import type { StoryGenerationScope, StoryProject } from './types'

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
        <CompactWorldArticle
          project={project} update={update} busy={busy} generateSection={generateSection}
          approveSection={approveSection} isSectionApproved={isSectionApproved}
          worldReady={worldReady} isMusicVideo={isMusicVideo} isTrailer={isTrailer} />
        <CompactCastArticle
          project={project} update={update} busy={busy} generateSection={generateSection}
          approveSection={approveSection} isSectionApproved={isSectionApproved}
          castReady={castReady} requiresVisualIdentities={requiresVisualIdentities}
          isMusicVideo={isMusicVideo} isTrailer={isTrailer} />
        <CompactSequenceArticle
          project={project} update={update} busy={busy} generateSection={generateSection}
          approveSection={approveSection} isSectionApproved={isSectionApproved}
          sequenceReady={sequenceReady} isMusicVideo={isMusicVideo} isTrailer={isTrailer} />
      </div>
    </section>
  )
}
