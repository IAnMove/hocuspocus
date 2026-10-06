import type { TFunction } from 'i18next'
import { useEffect, useState } from 'react'
import { Check, ExternalLink, Film, Loader2 } from 'lucide-react'
import * as api from '../../../api/client'
import { approveSeriesAttemptsBulk } from '../../../api/series'
import { outputProvenance } from '../../../lib/outputProvenance'
import { useUiTranslation } from '../../../i18n'
import { useSeriesStore } from '../store'
import { secondaryButton } from '../styles'
import { sectionId, type PartContext } from './context'
import { shotTakes, type TakeEntry } from './model'

/** The saved scene each take without one on record was exported from: the source video's sidecar names it
 * (``params.scene_file``, written when the export finished). Only the newest few takes are looked up. */
function useSourceScenes(workspace: string, takes: TakeEntry[]) {
  const [found, setFound] = useState<Record<string, string>>({})
  const sources = takes.slice(0, 4).filter(take => !take.sceneFilename && typeof take.asset.metadata?.source === 'string')
    .map(take => [take.attempt.id, take.asset.metadata.source as string] as const)
  const wanted = sources.map(([id, source]) => `${id}:${source}`).join('|')
  useEffect(() => {
    if (!wanted) return
    let alive = true
    for (const item of wanted.split('|')) {
      const [id, source] = [item.slice(0, item.indexOf(':')), item.slice(item.indexOf(':') + 1)]
      api.fetchOutputMetadata(source, workspace).then(metadata => {
        const scene = outputProvenance(metadata).sceneFile
        if (alive && scene) setFound(current => ({ ...current, [id]: scene }))
      }).catch(() => { /* a clip without a sidecar has no scene to open */ })
    }
    return () => { alive = false }
  }, [workspace, wanted])
  return found
}

/** When the take was made, and how: edited in an editor, or the generator that made it. */
function takeDetails(t: TFunction<'seriesLab'>, take: TakeEntry): string {
  const generator = take.asset.metadata?.generator
  return [take.attempt.completedAt ? new Date(take.attempt.completedAt).toLocaleString() : '', take.asset.metadata?.editedInEditor ? t('inspector.takes.edited') : '',
    typeof generator === 'string' ? generator : ''].filter(Boolean).join(' · ')
}

/** Who approved the take, when it was not a person. */
function approver(t: TFunction<'seriesLab'>, take: TakeEntry): string {
  const by = take.attempt.approvedBy
  return by && by !== 'user' ? ` · ${t(`review.decidedBy.${by}`)}` : ''
}

function TakeRow({ take, approved, selected, busy, onSelect, onApprove, onOpen }: {
  take: TakeEntry; approved: boolean; selected: boolean; busy: string; onSelect: (attemptId: string) => void; onApprove: () => void; onOpen: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const stage = take.attempt.reviewStage ? ` · ${t(`approval.stage.${take.attempt.reviewStage}`)}` : ''
  const button = `${secondaryButton} min-h-10 sm:min-h-0 sm:py-1`
  return <li className={`flex flex-wrap items-center gap-2 rounded-lg border p-1.5 ${selected ? 'border-violet-400/60 bg-violet-500/5' : 'border-border bg-bg-primary'}`}>
    <button type="button" className="shrink-0 overflow-hidden rounded" aria-label={t('inspector.takes.watch', { number: take.number })} onClick={() => onSelect(take.attempt.id)}>
      <img src={take.thumbnail} alt="" loading="lazy" className="aspect-video w-24 object-cover" /></button>
    <span className="min-w-0 flex-1 text-[11px]">
      <span className="block font-semibold text-text-primary">{t('inspector.takes.take', { number: take.number })}{stage}
        {take.attempt.reviewDecision === 'rejected' ? ` · ${t('inspector.takes.rejected')}` : ''}</span>
      <span className="block truncate text-[10px] text-text-muted">{takeDetails(t, take)}</span>
    </span>
    {approved ? <span className="inline-flex items-center gap-1 text-[10px] text-green-300"><Check size={12} />{t('inspector.takes.approved')}{approver(t, take)}</span>
      : <button type="button" className={button} disabled={Boolean(busy)} onClick={onApprove}>
        {busy === `approve-${take.attempt.id}` ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}{t('inspector.takes.use')}</button>}
    {take.sceneFilename && <button type="button" className={button} disabled={Boolean(busy)} onClick={onOpen}>
      <ExternalLink size={13} />{t(take.sceneFilename.endsWith('.world3d.scene.json') ? 'inspector.takes.open3d' : 'inspector.takes.open2d')}</button>}
  </li>
}

/** Every take of the shot: watch it above, use it as the shot's take, or open the scene it was made from. */
export function TakesPart({ context, selected, onSelect, onOpenEditor }: {
  context: PartContext; selected?: string; onSelect: (attemptId: string) => void
  onOpenEditor: (take: TakeEntry) => Promise<void>
}) {
  const { t } = useUiTranslation('seriesLab')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const listed = shotTakes(context.series, context.shot)
  const scenes = useSourceScenes(context.workspace, listed)
  const takes = listed.map(take => take.sceneFilename || !scenes[take.attempt.id] ? take : { ...take, sceneFilename: scenes[take.attempt.id] })
  const failed = context.shot.attempts.filter(item => item.status === 'failed').length
  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key); setError('')
    try { await task() } catch (reason) { setError((reason as Error).message) } finally { setBusy('') }
  }
  const approve = (take: TakeEntry) => run(`approve-${take.attempt.id}`, async () => {
    await useSeriesStore.getState().saveNow()
    const reply = await approveSeriesAttemptsBulk(context.workspace, context.series.id, context.episode.id, [{ shotId: context.shot.id, attemptId: take.attempt.id }])
    useSeriesStore.getState().acceptEpisode(context.series.id, reply.episode, reply.revision)
  })
  const id = sectionId(context.shot.id, 'takes')
  return <section id={id} aria-labelledby={`${id}-title`} data-testid={id} className="scroll-mt-20 rounded-xl border border-border bg-bg-secondary p-3">
    <header className="flex items-center gap-2"><Film size={14} className="text-violet-300" />
      <h4 id={`${id}-title`} className="text-xs font-semibold text-text-primary">{t('inspector.takes.title', { count: takes.length })}</h4>
      {failed > 0 && <span className="text-[10px] text-red-300">{t('inspector.takes.failed', { count: failed })}</span>}</header>
    {!takes.length && <p className="mt-2 text-[11px] text-text-muted">{t('inspector.takes.empty')}</p>}
    <ul className="mt-2 space-y-1.5">{takes.map(take => <TakeRow key={take.attempt.id} take={take} approved={take.attempt.id === context.shot.approvedAttemptId}
      selected={selected === take.attempt.id} busy={busy} onSelect={onSelect} onApprove={() => void approve(take)}
      onOpen={() => void run(`open-${take.attempt.id}`, () => onOpenEditor(take))} />)}</ul>
    {takes.some(take => take.sceneFilename) && <p className="mt-2 text-[10px] text-text-muted">{t('inspector.takes.editorHint')}</p>}
    {error && <p role="alert" className="mt-2 text-[11px] text-red-300">{error}</p>}
  </section>
}
