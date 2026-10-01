import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { loadShotView } from './api'
import { previewUrl } from './preview'
import type { ProductionShot, ShotView } from './types'

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

type LimitCode = keyof typeof LIMIT_KEYS

function isLimit(code: string): code is LimitCode {
  return Object.prototype.hasOwnProperty.call(LIMIT_KEYS, code)
}

export function ProductionShotsPanel({ view, workspace, onClose }: {
  view: ShotView
  workspace: string
  onClose: () => void
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
        {view.shots.map(shot => <ShotCard key={shot.id} shot={shot} workspace={workspace} />)}
      </ol>}
    </div>
  </div>
}

function ShotCard({ shot, workspace }: { shot: ProductionShot; workspace: string }) {
  const { t } = useTranslation('productionShots')
  return <li className="flex w-full flex-col gap-2 rounded-lg border border-border p-3">
    <h3>{t('order', { order: shot.order })}</h3>
    <ShotFacts shot={shot} />
    <TakeList shot={shot} workspace={workspace} />
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

function TakeList({ shot, workspace }: { shot: ProductionShot; workspace: string }) {
  const { t } = useTranslation('productionShots')
  if (shot.takes.length === 0) return null
  return <ul aria-label={t('takes')} className="flex flex-col gap-2">
    {shot.takes.map(take => <TakeRow key={take.id} file={take.file} id={take.id} selected={take.selected} workspace={workspace} />)}
  </ul>
}

function TakeRow({ file, id, selected, workspace }: { file: string | null; id: string; selected: boolean; workspace: string }) {
  const { t } = useTranslation('productionShots')
  const src = previewUrl(file, workspace)
  return <li className="flex flex-col gap-1 sm:flex-row sm:items-center">
    {src ? <img src={src} alt={file ?? id} className="h-24 w-auto max-w-full object-contain" /> : null}
    <span>{file ?? id}</span>
    {selected ? <span>{t('selected')}</span> : null}
  </li>
}

export function ShotLoader({ workspace, productionId, onClose }: {
  workspace: string
  productionId: string
  onClose: () => void
}) {
  const { t } = useTranslation('productionShots')
  const [view, setView] = useState<ShotView | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    loadShotView(workspace, productionId).then(
      result => { if (live) setView(result) },
      () => { if (live) setFailed(true) },
    )
    return () => { live = false }
  }, [workspace, productionId])
  if (failed) return <p>{t('loadFailed')}</p>
  if (!view) return <p>{t('loading')}</p>
  return <ProductionShotsPanel view={view} workspace={workspace} onClose={onClose} />
}
