import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { openSceneOutput } from '../../lib/sceneOutput'
import { sceneOutput } from '../video-editor/shotBoardModel'
import { useStore } from '../../stores/useStore'
import { applyMusicProductionTake, getMusicProduction, listMusicProductions, lockMusicProductionShot, requestMusicProductionShot, retakeMusicProductionShot, reviewMusicProductionShot, undoMusicProductionShot } from './api'
import { MusicProductionGrid } from './MusicProductionGrid'
import { ReviewMode } from './ReviewMode'
import type { MusicProductionCard, MusicProductionShot, ShotReviewAction } from './types'
import { requestOpenMontage } from './useOpenProductionMontage'

function applyReview(workspace: string, productionId: string, shot: string, action: ShotReviewAction): Promise<unknown> {
  if (action === 'lock' || action === 'unlock') {
    return lockMusicProductionShot(workspace, productionId, shot, action === 'lock')
  }
  return reviewMusicProductionShot(workspace, productionId, shot, action)
}

export function MusicProductionsPanel({ onClose }: { onClose: () => void }) {
  const workspace = useStore(state => state.activeWorkspace) || 'default'
  return <MusicProductionsBody key={workspace} workspace={workspace} onClose={onClose} />
}

function MusicProductionsBody({ workspace, onClose }: { workspace: string; onClose: () => void }) {
  const { t } = useUiTranslation('navigation')
  const [cards, setCards] = useState<MusicProductionCard[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [shots, setShots] = useState<MusicProductionShot[]>([])
  const [montage, setMontage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  useEffect(() => {
    let cancelled = false
    listMusicProductions(workspace).then(body => {
      if (!cancelled) setCards(body.productions || [])
    }).catch(reason => {
      if (cancelled) return
      setCards([])
      setError(reason instanceof Error ? reason.message : t('musicProductions.failed'))
    })
    return () => { cancelled = true }
  }, [workspace, t])

  const open = (card: MusicProductionCard) => {
    setSelected(card.production_id)
    setMontage(card.montage)
    setShots([])
    setError(null)
    setBusy(true)
    getMusicProduction(workspace, card.production_id).then(body => {
      setShots(body.shots || [])
      setMontage(body.production.montage)
    }).catch(reason => {
      setError(reason instanceof Error ? reason.message : t('musicProductions.failed'))
    }).finally(() => setBusy(false))
  }

  const run = (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    action().catch(reason => {
      setError(reason instanceof Error ? reason.message : t('musicProductions.failed'))
    }).finally(() => setBusy(false))
  }

  const refresh = async () => {
    if (!selected) return
    const body = await getMusicProduction(workspace, selected)
    setShots(body.shots || [])
  }

  return <div className="flex h-full min-h-0 flex-col">
    <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
      <h2 className="text-sm font-medium text-text-primary">{t('musicProductions.title')}</h2>
      <button type="button" className="rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover" onClick={onClose}>
        {t('musicProductions.close')}
      </button>
    </header>
    <div className="min-h-0 flex-1 overflow-auto p-4">
      {error ? <p className="mb-3 text-xs text-red-400">{error}</p> : null}
      {selected ? <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <button type="button" className="self-start rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover" onClick={() => { setSelected(null); setReviewing(false) }}>
            {t('musicProductions.back')}
          </button>
          <button type="button" className="self-start rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover" onClick={() => setReviewing(true)}>
            {t('musicProductions.review')}
          </button>
        </div>
        <MusicProductionGrid
          workspace={workspace}
          shots={shots}
          busy={busy}
          onOpenScene={sceneName => { void openSceneOutput(sceneOutput(workspace, sceneName)) }}
          onRetake={shot => run(() => retakeMusicProductionShot(workspace, selected, shot))}
          onUseTake={(shot, takeFile) => run(async () => {
            await applyMusicProductionTake(workspace, selected, shot, takeFile)
            const body = await getMusicProduction(workspace, selected)
            setShots(body.shots || [])
          })}
          onOpenMontage={() => { if (montage) requestOpenMontage(workspace, montage) }}
          onReview={(shot, action) => run(async () => {
            await applyReview(workspace, selected, shot, action)
            const body = await getMusicProduction(workspace, selected)
            setShots(body.shots || [])
          })}
        />
      </div> : <ProductionList cards={cards} onOpen={open} />}
    </div>
    {reviewing && selected ? <ReviewMode
      workspace={workspace}
      shots={shots}
      busy={busy}
      onClose={() => setReviewing(false)}
      onApprove={shot => run(async () => { await reviewMusicProductionShot(workspace, selected, shot, 'approved'); await refresh() })}
      onRequest={(shot, instruction) => requestMusicProductionShot(workspace, selected, shot, instruction, false)}
      onApply={(shot, instruction, preview) => run(async () => {
        await requestMusicProductionShot(workspace, selected, shot, instruction, true, preview.plan)
        await refresh()
      })}
      onOpenScene={sceneName => { void openSceneOutput(sceneOutput(workspace, sceneName)) }}
      onUseTake={(shot, takeFile) => run(async () => { await applyMusicProductionTake(workspace, selected, shot, takeFile); await refresh() })}
      onUndo={shot => {
        const historyId = shots.find(item => item.key === shot)?.review?.history_id
        if (!historyId) return
        run(async () => { await undoMusicProductionShot(workspace, selected, shot, historyId); await refresh() })
      }}
      onLock={(shot, locked) => run(async () => { await lockMusicProductionShot(workspace, selected, shot, locked); await refresh() })}
    /> : null}
  </div>
}

function ProductionList({ cards, onOpen }: { cards: MusicProductionCard[] | null; onOpen: (card: MusicProductionCard) => void }) {
  const { t } = useUiTranslation('navigation')
  if (!cards) return <p className="text-xs text-text-secondary">{t('musicProductions.loading')}</p>
  if (cards.length === 0) return <p className="text-xs text-text-secondary">{t('musicProductions.empty')}</p>
  return <div className="grid gap-3 sm:grid-cols-2">
    {cards.map(card => <button
      key={card.production_id}
      type="button"
      className="flex flex-col gap-2 rounded border border-border bg-bg-secondary p-3 text-left hover:bg-bg-hover"
      onClick={() => onOpen(card)}
    >
      {card.contact_sheet ? <img src={card.contact_sheet} alt={card.title} className="aspect-video w-full rounded object-cover" /> : null}
      <span className="text-sm font-medium text-text-primary">{card.title}</span>
      <span className="text-[11px] text-text-secondary">{t('musicProductions.status')}: {card.status}</span>
      <span className="text-[11px] text-text-secondary">{t('musicProductions.duration')}: {typeof card.duration === 'number' ? `${card.duration}s` : '—'}</span>
      <span className="text-[11px] text-text-primary">{t('musicProductions.open')}</span>
    </button>)}
  </div>
}
