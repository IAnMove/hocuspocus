import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { loadShotView, postShotAction } from './api'
import { previewUrl } from './preview'
import type { ProductionShot, ShotAction, ShotView } from './types'

const LIMIT_KEYS = {
  shots_unreadable: 'limits.shots_unreadable',
  series_unreadable: 'limits.series_unreadable',
  series_missing: 'limits.series_missing',
  episode_missing: 'limits.episode_missing',
  director_unreadable: 'limits.director_unreadable',
  montage_unreadable: 'limits.montage_unreadable',
  montage_missing: 'limits.montage_missing',
  shot_list_truncated: 'limits.shot_list_truncated',
  no_shots: 'limits.no_shots',
} as const

const REASON_KEYS = {
  shot_locked: 'reasons.shot_locked',
  origin_unsupported: 'reasons.origin_unsupported',
  no_take: 'reasons.no_take',
  no_history: 'reasons.no_history',
  no_scene: 'reasons.no_scene',
  regenerate_needs_runner: 'reasons.regenerate_needs_runner',
  unavailable: 'reasons.unavailable',
} as const

const NAMED_ACTIONS = {
  undo: 'actions.undo',
  reexport: 'actions.reexport',
  regenerate: 'actions.regenerate',
} as const

type LimitCode = keyof typeof LIMIT_KEYS
type ReasonCode = keyof typeof REASON_KEYS
type NamedAction = keyof typeof NAMED_ACTIONS
type ShotActionHandler = (body: Record<string, unknown>) => void

function isLimit(code: string): code is LimitCode {
  return Object.prototype.hasOwnProperty.call(LIMIT_KEYS, code)
}

function isReason(code: string): code is ReasonCode {
  return Object.prototype.hasOwnProperty.call(REASON_KEYS, code)
}

function isNamed(action: string): action is NamedAction {
  return Object.prototype.hasOwnProperty.call(NAMED_ACTIONS, action)
}

export function ProductionShotsPanel({ view, workspace, onClose, onAction }: {
  view: ShotView
  workspace: string
  onClose: () => void
  onAction?: ShotActionHandler
}) {
  const { t } = useTranslation('productionShots')
  const limits = view.limits.filter(code => code !== 'no_shots')
  return <div className="flex h-full min-h-0 w-full flex-col bg-bg-primary text-text-primary" role="dialog" aria-modal="true" aria-labelledby="production-shots-title">
    <header className="flex items-center justify-between gap-3 p-4">
      <h2 id="production-shots-title" className="text-lg">{t('title')}</h2>
      <button type="button" onClick={onClose} className="px-3 py-2">{t('close')}</button>
    </header>
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-6">
      <p>{view.project ? t('project', { kind: view.project.kind, id: view.project.id }) : t('noProject')}</p>
      <p>{t('status', { status: view.status })}</p>
      {limits.map(code => <p key={code}>{isLimit(code) ? t(LIMIT_KEYS[code]) : code}</p>)}
      {view.truncated ? <p>{t('truncated', { count: view.shots.length })}</p> : null}
      {view.shots.length === 0 ? <p>{t('empty')}</p> : <ol className="flex flex-col gap-3">
        {view.shots.map(shot => <ShotCard key={shot.id} shot={shot} workspace={workspace} onAction={onAction} />)}
      </ol>}
    </div>
  </div>
}

function ShotCard({ shot, workspace, onAction }: { shot: ProductionShot; workspace: string; onAction?: ShotActionHandler }) {
  const { t } = useTranslation('productionShots')
  const act: ShotActionHandler = body => onAction?.({ shot: shot.id, ...body })
  return <li className="flex w-full flex-col gap-2 rounded-lg border border-border p-3">
    <h3>{t('order', { order: shot.order })}</h3>
    <ShotFacts shot={shot} />
    <TakeList shot={shot} workspace={workspace} onAction={act} />
    <ShotActions shot={shot} onAction={act} />
  </li>
}

function kindLabel(kind: ProductionShot['text_kind']) {
  if (kind === 'lyric' || kind === 'dialogue' || kind === 'action') return kind
  return null
}

function TimeRange({ start, end }: { start: number | null; end: number | null }) {
  if (typeof start !== 'number' || typeof end !== 'number') return null
  return <span>{start}–{end}</span>
}

function Duration({ value }: { value: number | null }) {
  const { t } = useTranslation('productionShots')
  if (typeof value !== 'number') return null
  return <span>{t('duration', { value })}</span>
}

function ShotText({ text, kind }: { text: string | null; kind: ProductionShot['text_kind'] }) {
  const { t } = useTranslation('productionShots')
  const label = kindLabel(kind)
  if (!text) return null
  return <span>{label ? `${t(label)}: ` : ''}{text}</span>
}

function ReviewLine({ review }: { review: ProductionShot['review'] }) {
  const { t } = useTranslation('productionShots')
  if (!review) return null
  const locked = review.locked ? ` · ${t('locked')}` : ''
  return <span>{t('review')}: {review.status}{locked}</span>
}

function Technical({ status }: { status: string | null }) {
  const { t } = useTranslation('productionShots')
  if (!status) return null
  return <span>{t('technical')}: {status}</span>
}

function SceneLine({ scene }: { scene: ProductionShot['scene'] }) {
  const { t } = useTranslation('productionShots')
  if (!scene?.id && !scene?.kind) return null
  return <span>{t('scene')}: {[scene.kind, scene.id].filter(part => part).join(' ')}</span>
}

function StaleLine({ montage }: { montage: ProductionShot['montage'] }) {
  const { t } = useTranslation('productionShots')
  if (!montage || typeof montage.stale !== 'boolean') return null
  return <span>{montage.stale ? t('stale') : t('currentExport')}</span>
}

function ShotFacts({ shot }: { shot: ProductionShot }) {
  return <div className="flex flex-col gap-1">
    <TimeRange start={shot.start} end={shot.end} />
    <Duration value={shot.duration} />
    <ShotText text={shot.text} kind={shot.text_kind} />
    <ReviewLine review={shot.review} />
    <Technical status={shot.technical_status} />
    <SceneLine scene={shot.scene} />
    <StaleLine montage={shot.montage} />
  </div>
}

function TakeList({ shot, workspace, onAction }: { shot: ProductionShot; workspace: string; onAction?: ShotActionHandler }) {
  const { t } = useTranslation('productionShots')
  if (shot.takes.length === 0) return null
  const selectable = shot.actions?.find(item => item.action === 'select')?.enabled === true
  return <ul aria-label={t('takes')} className="flex flex-col gap-2">
    {shot.takes.map(take => <TakeRow key={take.id} file={take.file} id={take.id} selected={take.selected} workspace={workspace} selectable={selectable} onAction={onAction} />)}
  </ul>
}

function TakeRow({ file, id, selected, workspace, selectable, onAction }: {
  file: string | null
  id: string
  selected: boolean
  workspace: string
  selectable: boolean
  onAction?: ShotActionHandler
}) {
  const { t } = useTranslation('productionShots')
  const src = previewUrl(file, workspace)
  return <li className="flex flex-col gap-1 sm:flex-row sm:items-center">
    {src ? <img src={src} alt={file ?? id} className="h-24 w-auto max-w-full object-contain" /> : null}
    <span>{file ?? id}</span>
    {selected ? <span>{t('selected')}</span> : null}
    {!selected && selectable ? <button type="button" data-action="select" onClick={() => onAction?.({ action: 'select', take: id })}>{t('actions.select')}</button> : null}
  </li>
}

function Reason({ code }: { code: string | undefined }) {
  const { t } = useTranslation('productionShots')
  if (!code) return null
  return <span>{isReason(code) ? t(REASON_KEYS[code]) : code}</span>
}

function ShotActions({ shot, onAction }: { shot: ProductionShot; onAction?: ShotActionHandler }) {
  const actions = shot.actions ?? []
  if (actions.length === 0) return null
  return <div className="flex flex-col gap-1">
    {actions.map(item => <ActionControl key={item.action} item={item} shot={shot} onAction={onAction} />)}
  </div>
}

function ActionControl({ item, shot, onAction }: { item: ShotAction; shot: ProductionShot; onAction?: ShotActionHandler }) {
  if (item.action === 'select') return <DisabledReason item={item} labelKey="actions.select" />
  if (item.action === 'review') return <ReviewButtons item={item} onAction={onAction} />
  if (item.action === 'lock') return <LockButton item={item} shot={shot} onAction={onAction} />
  if (item.action === 'open_scene') return <SceneButton item={item} shot={shot} />
  if (!isNamed(item.action)) return null
  return <NamedButton item={item} action={item.action} shot={shot} onAction={onAction} />
}

function DisabledReason({ item, labelKey }: { item: ShotAction; labelKey: 'actions.select' }) {
  const { t } = useTranslation('productionShots')
  if (item.enabled) return null
  return <button type="button" disabled data-action={item.action}>{t(labelKey)} — <Reason code={item.reason} /></button>
}

function ReviewButtons({ item, onAction }: { item: ShotAction; onAction?: ShotActionHandler }) {
  const { t } = useTranslation('productionShots')
  if (!item.enabled) return <button type="button" disabled data-action="review">{t('actions.approve')} — <Reason code={item.reason} /></button>
  return <>
    <button type="button" data-action="review" data-status="approved" onClick={() => onAction?.({ action: 'review', status: 'approved' })}>{t('actions.approve')}</button>
    <button type="button" data-action="review" data-status="changes_requested" onClick={() => onAction?.({ action: 'review', status: 'changes_requested' })}>{t('actions.changes')}</button>
  </>
}

function LockButton({ item, shot, onAction }: { item: ShotAction; shot: ProductionShot; onAction?: ShotActionHandler }) {
  const { t } = useTranslation('productionShots')
  const unlock = shot.review?.locked === true
  return <button type="button" data-action="lock" disabled={!item.enabled} onClick={() => onAction?.({ action: 'lock', locked: !unlock })}>
    {t(unlock ? 'actions.unlock' : 'actions.lock')}
    {!item.enabled ? <> — <Reason code={item.reason} /></> : null}
  </button>
}

function SceneButton({ item, shot }: { item: ShotAction; shot: ProductionShot }) {
  const { t } = useTranslation('productionShots')
  return <button type="button" data-action="open_scene" disabled={!item.enabled} onClick={() => window.dispatchEvent(new CustomEvent('hocuspocus:production-shot-scene', { detail: { kind: shot.scene?.kind ?? null, id: shot.scene?.id ?? null } }))}>
    {t('actions.openScene')}
    {!item.enabled ? <> — <Reason code={item.reason} /></> : null}
  </button>
}

function NamedButton({ item, action, shot, onAction }: { item: ShotAction; action: NamedAction; shot: ProductionShot; onAction?: ShotActionHandler }) {
  const { t } = useTranslation('productionShots')
  return <button type="button" data-action={action} disabled={!item.enabled} onClick={() => onAction?.({ action, history_id: shot.review?.history_id })}>
    {t(NAMED_ACTIONS[action])}
    {!item.enabled ? <> — <Reason code={item.reason} /></> : null}
  </button>
}

export function ShotLoader({ workspace, productionId, onClose }: {
  workspace: string
  productionId: string
  onClose: () => void
}) {
  const { t } = useTranslation('productionShots')
  const [view, setView] = useState<ShotView | null>(null)
  const [failed, setFailed] = useState(false)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    let live = true
    loadShotView(workspace, productionId).then(
      result => { if (live) setView(result) },
      () => { if (live) setFailed(true) },
    )
    return () => { live = false }
  }, [workspace, productionId, nonce])
  if (failed) return <p>{t('loadFailed')}</p>
  if (!view) return <p>{t('loading')}</p>
  return <ProductionShotsPanel view={view} workspace={workspace} onClose={onClose} onAction={body => {
    const { shotId, request } = actionRequest(body, view.revision ?? 0)
    postShotAction(workspace, productionId, shotId, request).then(
      () => setNonce(current => current + 1),
      () => setFailed(true),
    )
  }} />
}

function actionRequest(body: Record<string, unknown>, revision: number) {
  const request: Record<string, unknown> = { expected_revision: revision }
  for (const [key, value] of Object.entries(body)) {
    if (key !== 'shot') request[key] = value
  }
  const shotId = typeof body.shot === 'string' ? body.shot : ''
  return { shotId, request }
}
