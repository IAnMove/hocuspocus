import type { TFunction } from 'i18next'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { SeriesShotEditReply } from '../../../api/seriesShotInspector'
import { Pill } from '../components'
import { ReviewPills, StageButtons, type ApprovalCardActions } from '../SeriesApprovalCard'
import { SeriesApprovalNotes } from '../SeriesApprovalNotes'
import { noteStage, reviewStage } from '../reviewModel'
import { openShotInEditor } from '../shotEditSession'
import { useSeriesStore } from '../store'
import { secondaryButton } from '../styles'
import type { ApprovalRender } from '../useApprovalRender'
import type { SeriesEpisode, SeriesProductionMode, SeriesProject, SeriesShot, SeriesShotReview } from '../types'
import { RerenderShot, sectionId, type PartContext } from './context'
import { Cast3DPart, CastPart } from './CastPart'
import { FxPart, PropsPart, SfxPart } from './CuesParts'
import { InspectorMedia } from './InspectorMedia'
import { markShotEdited, useEpisodeInspector, type SectionKey } from './inspectorStore'
import { LinesPart, type LineVoices } from './LinesPart'
import { keyPart, languageName, neighbours, originalLanguage, regeneration, shotParts, shotTakes, type InspectorPart } from './model'
import { CardPart, PlanPart } from './PlanPart'
import { RegenerateBar } from './RegenerateBar'
import { openShotScene3DPlan } from './scene3dPlan'
import { Scene3DPart } from './Scene3DPart'
import { SetPart, type SeriesEdits } from './SetPart'
import { SoundPart } from './SoundPart'
import { TakesPart } from './TakesPart'
import { useKitLibrary, useLineVoices, useShotView } from './useInspectorData'
import { VideoPart } from './VideoPart'

const typing = (target: EventTarget | null) => target instanceof HTMLElement
  && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))

/** What the save of a part changed, in words: approvals reset, lines a language version still lacks. */
function savedNotice(t: TFunction<'seriesLab'>, reply: SeriesShotEditReply, ui: string): string {
  const missing = Object.entries(reply.missingLines || {}).filter(([, lines]) => lines.length)
    .map(([language, lines]) => t('inspector.saved.missing', { language: languageName(language, ui), count: lines.length }))
  const parts = [...new Set(reply.changed.map(key => keyPart(key)).filter((part): part is SectionKey => Boolean(part)))]
    .map(part => t(`inspector.partNames.${part}`))
  return [t('inspector.saved.done', { keys: parts.join(', ') || reply.changed.join(', ') }), reply.approvalReset ? t('inspector.saved.reset') : '', ...missing]
    .filter(Boolean).join(' ')
}

/** Back to the grid, previous and next shot, and what this shot is. */
function TopBar({ series, shot, order, onClose, onNavigate }: {
  series: SeriesProject; shot: SeriesShot; order: string[]; onClose: () => void; onNavigate: (shotId: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const { index, total, previous, next } = neighbours(order, shot.id)
  const location = series.locations.find(item => item.id === shot.locationId)?.name
  const nav = `${secondaryButton} min-h-10 min-w-10 px-2 sm:min-h-0`
  return <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-border bg-bg-primary/95 py-2 backdrop-blur md:-top-4">
    <button type="button" className={`${secondaryButton} min-h-10 sm:min-h-0`} onClick={onClose}><ArrowLeft size={13} />{t('inspector.back')}</button>
    <button type="button" className={nav} disabled={!previous} aria-label={t('inspector.previous')} title={t('inspector.previous')}
      onClick={() => previous && onNavigate(previous)}><ChevronLeft size={15} /></button>
    <span className="text-[11px] text-text-muted">{t('inspector.position', { index: index + 1, total })}</span>
    <button type="button" className={nav} disabled={!next} aria-label={t('inspector.next')} title={t('inspector.next')}
      onClick={() => next && onNavigate(next)}><ChevronRight size={15} /></button>
    <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">{t('inspector.title', { order: shot.order })}
      <span className="ml-2 text-[11px] font-normal text-text-muted">{[location, t(`production.methods.${shot.productionMethod || 'generated_video'}`),
        t('approval.card.seconds', { seconds: Number(shot.durationSeconds.toFixed(2)) })].filter(Boolean).join(' · ')}</span></h3>
  </div>
}

/** ←/→ (or k/j) go to the previous and next shot and Escape closes, unless the user is typing. */
function useShotKeys(order: string[], shotId: string, onNavigate: (shotId: string) => void, onClose: () => void) {
  const { previous, next } = neighbours(order, shotId)
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (typing(event.target) || event.altKey || event.ctrlKey || event.metaKey) return
      const target = event.key === 'ArrowLeft' || event.key === 'k' ? previous : event.key === 'ArrowRight' || event.key === 'j' ? next : undefined
      if (target) { event.preventDefault(); onNavigate(target) } else if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [previous, next, onNavigate, onClose])
}

/** The shot's review: its status, the approve / request change buttons and the notes. */
function ReviewBox({ shot, entry, mode, hasTake, actions }: {
  shot: SeriesShot; entry: SeriesShotReview; mode: SeriesProductionMode; hasTake: boolean; actions: ApprovalCardActions
}) {
  const stage = reviewStage(mode, entry, shot)
  return <div className="space-y-2 rounded-xl border border-border bg-bg-secondary p-3">
    <div className="flex flex-wrap items-center gap-1.5"><Pill tone="blue">#{shot.order}</Pill>
      <span className="min-w-0 truncate font-mono text-[10px] text-text-muted" title={shot.id}>{shot.id}</span>
      <ReviewPills entry={entry} mode={mode} hasTake={hasTake} /></div>
    <div className="flex flex-wrap gap-2"><StageButtons shot={shot} stage={stage} status={entry[stage]} canApprove={stage === 'plan' || hasTake} actions={actions} /></div>
    <SeriesApprovalNotes key={`${shot.id}:${noteStage(mode, entry)}`} shotId={shot.id} entry={entry} stage={noteStage(mode, entry)} onSave={actions.saveNote(shot)} />
  </div>
}

/** Chips that jump to each part; a part with an unsaved draft is marked. */
function PartsNav({ shotId, parts, drafts }: { shotId: string; parts: InspectorPart[]; drafts: PartContext['drafts'] }) {
  const { t } = useUiTranslation('seriesLab')
  const unsaved = (part: InspectorPart) => part !== 'takes' && Boolean(drafts[part])
  return <nav aria-label={t('inspector.parts')} className="flex gap-1.5 overflow-x-auto pb-1">
    {parts.map(key => <a key={key} href={`#${sectionId(shotId, key)}`} className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] ${unsaved(key) ? 'border-amber-500/50 text-amber-200' : 'border-border text-text-secondary'}`}
      onClick={event => { event.preventDefault(); document.getElementById(sectionId(shotId, key))?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }) }}>
      {t(`inspector.partNames.${key}`)}{unsaved(key) ? ' •' : ''}</a>)}
  </nav>
}

/** One part of the shot in its own section. */
function ShotPart({ part, context, voices, edits, actions, selected, onSelect }: {
  part: InspectorPart; context: PartContext; voices: LineVoices; edits: SeriesEdits; actions: ApprovalCardActions
  selected?: string; onSelect: (attemptId: string) => void
}) {
  const { workspace, series, episode, shot } = context
  switch (part) {
    case 'cast': return <CastPart context={context} onOpenFaceRig={actions.openFaceRig} />
    case 'cast3d': return <Cast3DPart context={context} onOpenFaceRig={actions.openFaceRig} />
    case 'lines': return <LinesPart context={context} voices={voices} />
    case 'set': return <SetPart context={context} edits={edits} />
    case 'props': return <PropsPart context={context} />
    case 'fx': return <FxPart context={context} />
    case 'sfx': return <SfxPart context={context} />
    case 'sound': return <SoundPart context={context} />
    case 'plan': return <PlanPart context={context} />
    case 'card': return <CardPart context={context} />
    case 'scene3d': return <Scene3DPart context={context} onOpenEditor={() => openShotScene3DPlan(workspace, series, episode, shot)} />
    case 'video': return <VideoPart context={context} />
    default: return <TakesPart context={context} selected={selected} onSelect={onSelect}
      onOpenEditor={take => openShotInEditor(workspace, series, episode, shot, take.sceneFilename)} />
  }
}

/**
 * One shot opened from the Validation grid: its take (or plan) on top, its review and the one call to action to
 * re-render it, then every part of the shot in its own section, each with Edit: characters, lines and their voices,
 * location and set, props, effects, sounds, music and foley, the 3D scene, the video take and the takes.
 */
export function SeriesShotInspector({ workspace, series, episode, shot, entry, mode, inspector, order, render, actions, edits, onClose, onNavigate }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot; entry: SeriesShotReview; mode: SeriesProductionMode
  inspector: string; order: string[]; render: ApprovalRender; actions: ApprovalCardActions; edits: SeriesEdits
  onClose: () => void; onNavigate: (shotId: string) => void
}) {
  const { t, i18n } = useUiTranslation('seriesLab')
  const { view, error: viewError, replace } = useShotView(workspace, series.id, episode.id, shot.id, series.revision)
  const voices = useLineVoices(workspace, series.id, episode.id, shot.id)
  const kits = useKitLibrary(workspace)
  const state = useEpisodeInspector(inspector)
  const editShot = useSeriesStore(store => store.editShot)
  const [selected, setSelected] = useState<string>()
  const takes = shotTakes(series, shot)
  const save = useCallback(async (changes: Record<string, unknown>) => {
    const reply = await editShot(episode.id, { shot: shot.id, changes })
    replace(reply.shot)
    markShotEdited(inspector, shot.id, Date.now())
    if ('lines' in changes) voices.refresh()
    return savedNotice(t, reply, i18n.language)
  }, [editShot, episode.id, shot.id, replace, inspector, voices, t, i18n.language])
  useShotKeys(order, shot.id, onNavigate, onClose)
  const context: PartContext = useMemo(() => ({
    workspace, series, episode, shot, script: view?.script, inspector, drafts: state.drafts[shot.id] || {}, save, kits,
    language: originalLanguage(view?.script?.lines, voices.language),
  }), [workspace, series, episode, shot, view, inspector, state.drafts, save, kits, voices.language])
  const plan = regeneration(shot, voices.voices, state.edited[shot.id])
  const parts = shotParts(shot, view?.script)
  const rerender = plan.renders || plan.foley ? { label: t(plan.renders ? 'approval.card.rerender' : 'inspector.regenerate.foley'),
    run: () => actions.rerender(shot), busy: render.busy || render.live } : undefined
  return <div className="min-w-0 space-y-3 pb-12" data-testid="series-shot-inspector" aria-label={t('inspector.title', { order: shot.order })} role="region">
    <TopBar series={series} shot={shot} order={order} onClose={onClose} onNavigate={onNavigate} />
    <div className="@container">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 @5xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-3 @5xl:sticky @5xl:top-14 @5xl:self-start">
          <InspectorMedia series={series} shot={shot} takes={takes} selected={selected} onSelect={setSelected} kits={kits} />
          <ReviewBox shot={shot} entry={entry} mode={mode} hasTake={takes.length > 0} actions={actions} />
          <RegenerateBar series={series} shot={shot} plan={plan} job={render.job} busy={render.busy} error={render.error} onRender={() => actions.rerender(shot)} />
          <PartsNav shotId={shot.id} parts={parts} drafts={context.drafts} />
        </div>
        <div className="min-w-0 space-y-3">
          {viewError && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">{viewError}</p>}
          {!view && !viewError && <p className="text-[11px] text-text-muted">{t('inspector.loading')}</p>}
          <RerenderShot.Provider value={rerender}>{view && parts.map(part => <ShotPart key={part} part={part} context={context} voices={voices}
            edits={edits} actions={actions} selected={selected} onSelect={setSelected} />)}</RerenderShot.Provider>
        </div>
      </div>
    </div>
  </div>
}
