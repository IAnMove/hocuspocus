import { useState } from 'react'
import { Check, Loader2, RotateCcw, Trash2, WandSparkles, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import {
  animationGroups, animationReference, animationState, animationsOf, canAddAnimation, freeAnimationId, kitAnimations, kitCustomDefs, localized, templateControls,
  type AnimationDef, type AnimationState, type KitAnimation,
} from '../../lib/characterAnimations'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import type { CharacterKit, CharacterKitReviewState } from '../../lib/characterKit'
import { AnimationSheetPlayer } from './AnimationSheetPlayer'
import { CustomAnimationForm } from './CustomAnimationForm'
import type { AnimationRun } from './useCharacterAnimations'
import { useCharacterAnimations } from './useCharacterAnimations'
import { useCharacterKitLibrary } from './useCharacterKitLibrary'

const control = 'min-h-9 rounded-lg border border-border bg-bg-primary px-3 text-xs disabled:opacity-40'
const small = 'inline-flex min-h-8 items-center gap-1 rounded-md border border-border px-2 text-[11px] disabled:opacity-40'
const BADGE: Record<AnimationState, string> = {
  none: 'border-border text-text-muted', pending: 'border-amber-400/40 text-amber-200',
  approved: 'border-emerald-400/40 text-emerald-200', rejected: 'border-red-400/40 text-red-200',
}

type Actions = {
  busy: boolean; active?: AnimationRun
  make: (def: AnimationDef, remake?: string) => void; cancel: () => void
  review: (id: string, state: CharacterKitReviewState) => void; remove: (id: string) => void
}

function RunProgress({ def, run }: { def: AnimationDef; run: AnimationRun }) {
  const { t, i18n } = useUiTranslation('characters')
  return <div className="space-y-1" role="status" data-testid="animation-progress">
    <p className="text-[11px] text-text-secondary">{t(run.stage === 'sheet' ? 'animations.stage.sheet' : 'animations.stage.poses')}</p>
    <ul className="space-y-0.5 text-[11px]">{run.takes.map(take => {
      const pose = def.poses.find(item => item.id === take.id)
      return <li key={take.id} className={take.status === 'failed' ? 'text-red-300' : 'text-text-muted'}>
        {pose ? localized(pose.label, i18n.language) : take.id}: {t(`animations.pose.${take.status}`)}{take.error ? ` — ${take.error}` : ''}
      </li>
    })}</ul>
  </div>
}

function MadeAnimation({ def, made, actions }: { def: AnimationDef; made: KitAnimation; actions: Actions }) {
  const { t, i18n } = useUiTranslation('characters')
  const controls = Object.entries(templateControls(made, def.template)).map(([key, value]) => `${key} ${value}`).join(', ')
  return <div className="grid gap-3 sm:grid-cols-[14rem_minmax(0,1fr)]">
    <AnimationSheetPlayer animation={made} title={localized(def.title, i18n.language)} />
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-1.5">{made.frames.map(frame => {
        const pose = def.poses.find(item => item.id === frame.id)
        return <li key={frame.id} className="w-16 space-y-1 text-center">
          <img src={frame.source} alt={pose ? localized(pose.label, i18n.language) : frame.id} className="aspect-[3/4] w-full rounded border border-border bg-bg-tertiary object-contain" />
          <button type="button" disabled={actions.busy} onClick={() => actions.make(def, frame.id)} className="w-full text-[10px] text-cyan-200 underline disabled:opacity-40"
            aria-label={t('animations.remakePose', { pose: pose ? localized(pose.label, i18n.language) : frame.id })}>{t('animations.remake')}</button>
        </li>
      })}</ul>
      <p className="text-[11px] text-text-muted">{t('animations.plays', { template: def.template, controls })}</p>
      <div className="flex flex-wrap gap-1.5">
        <button type="button" disabled={actions.busy || made.reviewState === 'approved'} className={small} onClick={() => actions.review(def.id, 'approved')}><Check size={12} />{t('animations.approve')}</button>
        <button type="button" disabled={actions.busy || made.reviewState === 'rejected'} className={small} onClick={() => actions.review(def.id, 'rejected')}><X size={12} />{t('animations.reject')}</button>
        <button type="button" disabled={actions.busy} className={small} onClick={() => actions.make(def)}><RotateCcw size={12} />{t('animations.makeAgain')}</button>
        <button type="button" disabled={actions.busy} className={small} onClick={() => actions.remove(def.id)}><Trash2 size={12} />{t('animations.delete')}</button>
      </div>
    </div>
  </div>
}

function AnimationCard({ def, kit, actions }: { def: AnimationDef; kit: CharacterKit; actions: Actions }) {
  const { t, i18n } = useUiTranslation('characters')
  const state = animationState(kit, def.id)
  const made = kitAnimations(kit)[def.id]
  const running = actions.active?.kitId === kit.id && actions.active.animationId === def.id ? actions.active : undefined
  return <article data-testid={`animation-${def.id}`} className="space-y-2 rounded-lg border border-border bg-bg-secondary p-3">
    <header className="flex items-start justify-between gap-2">
      <div className="min-w-0 flex-1">
        <h5 className="text-sm font-medium">{localized(def.title, i18n.language)}</h5>
        <p className="text-[11px] text-text-muted">{def.custom ? t('animations.custom.summary', { count: def.poses.length, view: t(`animations.view.${def.view}`) }) : localized(def.summary, i18n.language)}</p>
      </div>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${BADGE[state]}`}>{t(`animations.state.${state}`)}</span>
    </header>
    {running && <RunProgress def={def} run={running} />}
    {made && !running && <MadeAnimation def={def} made={made} actions={actions} />}
    {!made && !running && <p className="text-[11px] text-text-muted">{t('animations.posesCount', { count: def.poses.length })}</p>}
    {(!made || running) && <div className="flex gap-2">
      <button type="button" disabled={actions.busy} className={`${small} text-cyan-200`} onClick={() => actions.make(def)}>
        {running && actions.busy ? <Loader2 size={12} className="animate-spin" /> : <WandSparkles size={12} />}
        {t(running ? (actions.busy ? 'animations.working' : 'animations.tryAgain') : 'animations.make')}</button>
      {running && actions.busy && <button type="button" className={small} onClick={actions.cancel}>{t('animations.cancel')}</button>}
    </div>}
  </article>
}

/** The small animations of a saved character: andar, gestos and the usual anime expressions. Each one is a few poses of the
 * same figure, made with Qwen from the character's own picture, keyed and joined into a sprite sheet that the Video 2D cards play. */
export function CharacterAnimationsPanel({ workspace }: { workspace: string }) {
  const { t, i18n } = useUiTranslation('characters')
  const models = useStore(state => state.models)
  const { kits, error: loadError, loading, reload } = useCharacterKitLibrary(workspace)
  const [kitId, setKitId] = useState('')
  const [modelId, setModelId] = useState('')
  const usable = kits.filter(kit => animationReference(kit))
  const kit = usable.find(item => item.id === kitId) ?? usable[0]
  const imageModels = characterImageModels(models, false)
  const model = imageModels.some(item => item.model_type === modelId) ? modelId : preferredCharacterImageModel(imageModels, false)
  const work = useCharacterAnimations(workspace, reload)
  // An animation the author just described is not on the kit until its first run is saved: it shows while that run is on screen.
  const [described, setDescribed] = useState<AnimationDef>()
  const actions: Actions = {
    busy: work.busy, active: work.run, cancel: work.cancel,
    make: (def, remake) => { if (kit && model) void work.start(kit, def, model, remake) },
    review: (id, state) => { if (kit) void work.review(kit.id, id, state) },
    remove: id => { if (kit) void work.remove(kit.id, id) },
  }
  return <div className="space-y-4" data-testid="character-animations">
    <p className="text-sm text-text-muted">{t('animations.intro')}</p>
    {loadError && <p role="alert" className="text-sm text-red-300">{loadError}</p>}
    {!loading && !usable.length && !loadError && <p className="rounded-lg border border-dashed border-border p-3 text-sm text-text-muted">{t('animations.noKits')}</p>}
    {kit && <div className="flex flex-wrap gap-3">
      <label className="text-xs text-text-secondary">{t('animations.kit')}
        <select value={kit.id} disabled={work.busy} onChange={event => setKitId(event.target.value)} className={`${control} mt-1 block min-w-48`}>
          {usable.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
      <label className="text-xs text-text-secondary">{t('lips.imageModel')}
        <select value={model} disabled={work.busy} onChange={event => setModelId(event.target.value)} className={`${control} mt-1 block min-w-48`}>
          {!imageModels.length && <option value="">{t('lips.noImageModel')}</option>}
          {imageModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
        </select></label>
    </div>}
    {work.error && <p role="alert" className="text-sm text-red-300">{work.error}</p>}
    {work.saved && <p role="status" className="text-sm text-emerald-200">{t('animations.saved')}</p>}
    {kit && animationGroups.map(group => {
      const kept = group.id === 'custom' ? kitCustomDefs(kit) : animationsOf(group.id)
      const showing = group.id === 'custom' && described && work.run?.animationId === described.id && !kept.some(def => def.id === described.id) ? [...kept, described] : kept
      const done = showing.filter(def => kitAnimations(kit)[def.id]).length
      return <details key={group.id} open={group.id === 'cycle' || group.id === 'custom' || done > 0} className="space-y-2" data-testid={`animation-group-${group.id}`}>
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-text-secondary">
          {localized(group.title, i18n.language)} <span className="font-normal normal-case text-text-muted">· {t('animations.groupCount', { done, total: showing.length })}</span></summary>
        <div className="mt-2 grid gap-3 md:grid-cols-2">{showing.map(def => <AnimationCard key={def.id} def={def} kit={kit} actions={actions} />)}</div>
        {group.id === 'custom' && (canAddAnimation(kit)
          ? <CustomAnimationForm disabled={work.busy || !model} freeId={name => freeAnimationId(kit, name)} onCreate={def => { setDescribed(def); actions.make(def) }} />
          : <p className="text-[11px] text-text-muted">{t('animations.custom.full')}</p>)}
      </details>
    })}
  </div>
}
