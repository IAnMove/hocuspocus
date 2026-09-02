import { Check, Loader2, Plus, Sparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, requiredPreparationButton, type StoryGenerationOptions } from './storyLabChrome'
import { storyId } from './model'
import { CompactBeatEditor } from './CompactBeatEditor'
import { CompactPrepStatus } from './CompactPrepStatus'
import { useStoryLabVisuals } from './storyLabVisuals'
import type { StoryGenerationScope, StoryProject } from './types'

export function CompactSequenceArticle({
  project, update, busy, generateSection, approveSection, isSectionApproved, sequenceReady, isMusicVideo, isTrailer,
}: {
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  generateSection: (scope: StoryGenerationScope, options?: StoryGenerationOptions) => void
  approveSection: (scope: keyof StoryProject['approvals']) => void
  isSectionApproved: (scope: keyof StoryProject['approvals']) => boolean
  sequenceReady: boolean
  isMusicVideo: boolean
  isTrailer: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const { referenceBatchBusy } = useStoryLabVisuals()
  return (
    <article id="story-review-structure" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">3 · {isMusicVideo ? t('compact.sequenceMusic') : isTrailer ? t('compact.sequenceTrailer') : t('compact.sequenceQuick')}</h4>
          <p className="text-[9px] text-text-muted">{isMusicVideo ? t('compact.sequenceHintMusic') : isTrailer ? t('compact.sequenceHintTrailer') : t('compact.sequenceHintQuick')}</p>
        </div>
        <CompactPrepStatus ready={sequenceReady} approved={isSectionApproved('structure')} />
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
  )
}
