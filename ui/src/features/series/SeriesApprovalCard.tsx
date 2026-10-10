import { Check, MessageSquare, Undo2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Pill } from './components'
import { greenButton, secondaryButton } from './styles'
import type { SaveNote } from './SeriesApprovalNotes'
import type { SeriesProductionMode, SeriesReviewStatus, SeriesShot, SeriesShotReview } from './types'

/** The review controls a shot has in the Validation tab, on its tile and in the inspector. */
const REVIEW_TONE: Record<SeriesReviewStatus, 'neutral' | 'green' | 'amber'> = { pending: 'neutral', approved: 'green', changes: 'amber' }
const button = 'min-h-10 sm:min-h-0'

export interface ApprovalCardActions {
  review: (shot: SeriesShot, stage: 'plan' | 'preview', status: SeriesReviewStatus) => Promise<void>
  saveNote: (shot: SeriesShot) => SaveNote
  rerender: (shot: SeriesShot) => void
  openFaceRig?: (characterId: string, poseId?: string) => void
}

/** The plan and preview status of a shot, as the episode's mode asks for them; an agent's, the Wizard's or a
 * production's own decision says so (a person's needs no label). */
export function ReviewPills({ entry, mode, hasTake, quiet }: { entry: SeriesShotReview; mode: SeriesProductionMode; hasTake: boolean; quiet?: boolean }) {
  const { t } = useUiTranslation('seriesLab')
  const decider = (by?: string) => by === 'agent' || by === 'wizard' || by === 'server' ? ` · ${t(`review.decidedBy.${by}`)}` : ''
  // On a tile of an episode produced all at once, only a decision is worth a label.
  if (quiet && mode === 'direct' && entry.preview === 'pending') return null
  return <>
    {mode !== 'direct' && <Pill tone={REVIEW_TONE[entry.plan]}>{t('approval.card.planStatus', { status: t(`approval.status.${entry.plan}`) })}{decider(entry.planBy)}</Pill>}
    {(mode === 'preview' || (mode === 'direct' && hasTake)) && <Pill tone={REVIEW_TONE[entry.preview]}>
      {t('approval.card.previewStatus', { status: t(`approval.status.${entry.preview}`) })}{decider(entry.previewBy)}</Pill>}
  </>
}

/** Approve the stage the shot is at (its plan, then its preview), ask for a change, or undo the decision. */
export function StageButtons({ shot, stage, status, canApprove, actions, compact, onRequestChange }: {
  shot: SeriesShot; stage: 'plan' | 'preview'; status: SeriesReviewStatus; canApprove: boolean; actions: ApprovalCardActions
  compact?: boolean; onRequestChange?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const requestChange = () => {
    void actions.review(shot, stage, 'changes')
    onRequestChange?.()
    document.getElementById(`series-approval-note-${shot.id}`)?.focus()
  }
  if (status !== 'pending') return <button type="button" className={`${secondaryButton} ${button}`} onClick={() => void actions.review(shot, stage, 'pending')}>
    <Undo2 size={13} />{t('approval.card.undo')}</button>
  return <>
    <button type="button" className={`${greenButton} ${button}`} disabled={!canApprove} onClick={() => void actions.review(shot, stage, 'approved')}>
      <Check size={13} />{t(stage === 'plan' ? 'approval.card.approvePlan' : 'approval.card.approvePreview')}</button>
    {!compact && <button type="button" className={`${secondaryButton} ${button}`} onClick={requestChange}><MessageSquare size={13} />{t('approval.card.requestChange')}</button>}
  </>
}
