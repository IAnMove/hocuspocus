import { useState } from 'react'
import { Check, Edit3, ExternalLink, MessageSquare, Play, RotateCcw, Smile, Undo2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Pill } from './components'
import { greenButton, secondaryButton } from './styles'
import {
  canRenderOnServer, latestTakeMedia, noteStage, reviewStage, shotCast, shotDressing, shotLines, type TakeMedia,
} from './reviewModel'
import { SeriesApprovalNotes, type SaveNote } from './SeriesApprovalNotes'
import { SeriesShotEditPanel } from './SeriesShotEditPanel'
import type { SeriesEpisode, SeriesProductionMode, SeriesProject, SeriesReviewStatus, SeriesShot, SeriesShotReview } from './types'

const TONE: Record<SeriesReviewStatus, 'neutral' | 'green' | 'amber'> = { pending: 'neutral', approved: 'green', changes: 'amber' }
const button = 'min-h-10 sm:min-h-0'

function TakePreview({ media, order }: { media?: TakeMedia; order: number }) {
  const { t } = useUiTranslation('seriesLab')
  const [playing, setPlaying] = useState(false)
  const frame = 'relative aspect-video w-full overflow-hidden rounded-lg bg-black/70 sm:w-56 sm:shrink-0'
  if (!media) return <div className={`${frame} flex items-center justify-center text-[11px] text-text-muted`}>{t('approval.card.noPreview')}</div>
  if (playing) return <video className={`${frame} object-contain`} src={media.url} controls autoPlay playsInline preload="metadata" />
  return <button type="button" className={frame} aria-label={t('approval.card.play', { order })} onClick={() => setPlaying(true)}>
    <img src={media.thumbnail} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover opacity-80" />
    <span className="relative flex h-full items-center justify-center"><span className="rounded-full bg-black/70 p-3 text-white"><Play size={20} /></span></span>
  </button>
}

function TakeMarker({ shot, media }: { shot: SeriesShot; media?: TakeMedia }) {
  const { t } = useUiTranslation('seriesLab')
  if (!media) return null
  const approved = media.attempt.id === shot.approvedAttemptId
  const stage = media.attempt.reviewStage
  return <Pill tone={stage === 'preview' ? 'violet' : approved ? 'green' : 'blue'}>
    {t(stage === 'preview' ? 'approval.card.draftPreview' : stage === 'final' ? 'approval.card.finalTake' : approved ? 'approval.card.approvedTake' : 'approval.card.take')}
  </Pill>
}

function CastChips({ series, shot, onOpenFaceRig }: { series: SeriesProject; shot: SeriesShot; onOpenFaceRig?: (characterId: string, poseId?: string) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const cast = shotCast(series, shot)
  if (!cast.length) return null
  return <ul aria-label={t('approval.card.cast')} className="flex flex-wrap gap-1.5">
    {cast.map((member, index) => <li key={`${member.characterId}-${index}`} className="flex items-center gap-1 rounded-full border border-border bg-bg-tertiary py-0.5 pl-2 pr-0.5">
      <span className="text-text-primary">{member.name}</span>
      {member.poseId && <span className="text-text-muted">· {member.poseId}</span>}
      {onOpenFaceRig && <button type="button" className="flex min-h-8 min-w-8 items-center justify-center rounded-full text-violet-300 hover:bg-bg-hover"
        title={t('approval.card.faceRig', { name: member.name })} aria-label={t('approval.card.faceRig', { name: member.name })}
        onClick={() => onOpenFaceRig(member.characterId, member.poseId)}><Smile size={14} /></button>}
    </li>)}
  </ul>
}

function ShotFacts({ series, shot, onOpenFaceRig }: { series: SeriesProject; shot: SeriesShot; onOpenFaceRig?: (characterId: string, poseId?: string) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const location = series.locations.find(item => item.id === shot.locationId)?.name || shot.locationId
  const lines = shotLines(series, shot)
  const dressing = shotDressing(shot).map(item => t(`approval.card.${item.key}`, item.values))
  return <div className="min-w-0 flex-1 space-y-1.5 text-[11px] text-text-secondary">
    <p className="flex flex-wrap gap-x-3 gap-y-0.5">
      {location && <span>{t('approval.card.location', { name: location })}</span>}
      <span>{t('approval.card.framing', { value: shot.layout2d?.framing || shot.framing || '—' })}</span>
      <span>{t('approval.card.camera', { value: shot.layout2d?.camera || shot.camera || '—' })}</span>
    </p>
    <CastChips series={series} shot={shot} onOpenFaceRig={onOpenFaceRig} />
    {lines.length > 0 ? <ol className="space-y-0.5">
      {lines.map(line => <li key={line.id}><span className="font-semibold text-text-primary">{line.speaker}:</span> {line.text}</li>)}
    </ol> : <p className="text-text-muted">{t('approval.card.noLines')}</p>}
    {shot.action && <p className="text-text-muted">{shot.action}</p>}
    {dressing.length > 0 && <p className="text-[10px] text-text-muted">{dressing.join(' · ')}</p>}
  </div>
}

export interface ApprovalCardActions {
  review: (shot: SeriesShot, stage: 'plan' | 'preview', status: SeriesReviewStatus) => Promise<void>
  saveNote: (shot: SeriesShot) => SaveNote
  rerender: (shot: SeriesShot) => void
  openEditor: (shot: SeriesShot) => void
  openFaceRig?: (characterId: string, poseId?: string) => void
  changeShot: (shot: SeriesShot) => void
}

function StageButtons({ shot, stage, status, canApprove, actions }: {
  shot: SeriesShot; stage: 'plan' | 'preview'; status: SeriesReviewStatus; canApprove: boolean; actions: ApprovalCardActions
}) {
  const { t } = useUiTranslation('seriesLab')
  const requestChange = () => {
    void actions.review(shot, stage, 'changes')
    document.getElementById(`series-approval-note-${shot.id}`)?.focus()
  }
  if (status !== 'pending') return <button type="button" className={`${secondaryButton} ${button}`} onClick={() => void actions.review(shot, stage, 'pending')}>
    <Undo2 size={13} />{t('approval.card.undo')}</button>
  return <>
    <button type="button" className={`${greenButton} ${button}`} disabled={!canApprove} onClick={() => void actions.review(shot, stage, 'approved')}>
      <Check size={13} />{t(stage === 'plan' ? 'approval.card.approvePlan' : 'approval.card.approvePreview')}</button>
    <button type="button" className={`${secondaryButton} ${button}`} onClick={requestChange}><MessageSquare size={13} />{t('approval.card.requestChange')}</button>
  </>
}

export function SeriesApprovalCard({ workspace, series, episode, shot, entry, mode, renderLive, actions, saveNow }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot; entry: SeriesShotReview
  mode: SeriesProductionMode; renderLive: boolean; actions: ApprovalCardActions; saveNow: () => Promise<unknown>
}) {
  const { t } = useUiTranslation('seriesLab')
  const [editing, setEditing] = useState(false)
  const media = latestTakeMedia(series, shot)
  // An agent's, the Wizard's or a production's own decision says so; a person's needs no label.
  const decider = (by?: string) => by === 'agent' || by === 'wizard' || by === 'server' ? ` · ${t(`review.decidedBy.${by}`)}` : ''
  const stage = reviewStage(mode, entry, shot)
  const status = entry[stage]
  return <article id={`series-approval-${shot.id}`} data-testid={`series-approval-${shot.id}`}
    className={`scroll-mt-16 space-y-2 rounded-xl border bg-bg-primary p-3 ${status === 'changes' ? 'border-amber-500/40' : status === 'approved' ? 'border-green-500/30' : 'border-border'}`}>
    <div className="flex flex-wrap items-center gap-1.5">
      <Pill tone="blue">#{shot.order}</Pill>
      <span className="min-w-0 max-w-[12rem] truncate font-mono text-[10px] text-text-muted" title={shot.id}>{shot.id}</span>
      <Pill>{t(`production.methods.${shot.productionMethod || 'generated_video'}`)}</Pill>
      <Pill>{t('approval.card.seconds', { seconds: Number(shot.durationSeconds.toFixed(2)) })}</Pill>
      {mode !== 'direct' && <Pill tone={TONE[entry.plan]}>{t('approval.card.planStatus', { status: t(`approval.status.${entry.plan}`) })}{decider(entry.planBy)}</Pill>}
      {(mode === 'preview' || (mode === 'direct' && media)) && <Pill tone={TONE[entry.preview]}>{t('approval.card.previewStatus', { status: t(`approval.status.${entry.preview}`) })}{decider(entry.previewBy)}</Pill>}
      <TakeMarker shot={shot} media={media} />
    </div>
    <div className="flex flex-col gap-3 sm:flex-row">
      <TakePreview media={media} order={shot.order} />
      <ShotFacts series={series} shot={shot} onOpenFaceRig={actions.openFaceRig} />
    </div>
    <div className="flex flex-wrap gap-2">
      <StageButtons shot={shot} stage={stage} status={status} canApprove={stage === 'plan' || Boolean(media)} actions={actions} />
      <button type="button" className={`${secondaryButton} ${button}`} aria-expanded={editing} onClick={() => setEditing(value => !value)}><Edit3 size={13} />{t('approval.card.edit')}</button>
      {media?.sceneFilename && <button type="button" className={`${secondaryButton} ${button}`} onClick={() => actions.openEditor(shot)}><ExternalLink size={13} />{t('approval.card.openEditor')}</button>}
      {canRenderOnServer(shot) && <button type="button" className={`${secondaryButton} ${button}`} disabled={renderLive} onClick={() => actions.rerender(shot)}><RotateCcw size={13} />{t('approval.card.rerender')}</button>}
    </div>
    <SeriesApprovalNotes key={`${shot.id}:${noteStage(mode, entry)}`} shotId={shot.id} entry={entry} stage={noteStage(mode, entry)} onSave={actions.saveNote(shot)} />
    {editing && <SeriesShotEditPanel workspace={workspace} series={series} episode={episode} shot={shot} onChange={actions.changeShot} saveNow={saveNow} />}
  </article>
}
