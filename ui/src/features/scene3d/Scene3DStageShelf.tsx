import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { listWorld3DStageCards, type World3DLibraryCard } from '../../api/world3dWorkspace'
import { Scene3DDocumentThumb } from './Scene3DTemplateThumb'
import { gridFocusTarget } from './shotLibraryState'
import { filterStageCards, INVALID_STAGE_DOCUMENT, loadStageDocument, stageLine, stageMarks, stageShape, stageTitle } from './stageShelf'
import { packFromStage } from './templateLibraryModel'
import type { World3DUserTemplate } from './userTemplates.ts'

/** A stage card and the editable document it opens. */
export type StageChoice = { card: World3DLibraryCard; pack: World3DUserTemplate }

const reasonOf = (reason: unknown) => reason instanceof Error ? reason.message : String(reason)

function StageCard({ card, workspace, locale, selected, onPick, onUse }: {
  card: World3DLibraryCard; workspace: string; locale: 'en' | 'es'; selected: boolean; onPick: () => void; onUse: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const load = useCallback(() => loadStageDocument(workspace, card.id), [workspace, card.id])
  return <button type="button" data-shot-card onClick={onPick} onDoubleClick={onUse} aria-pressed={selected} data-testid={`world3d-stage-${card.id}`}
    className={`overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-cyan-200 ${selected ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary hover:border-cyan-300/50'}`}>
    <Scene3DDocumentThumb id={card.id} load={load} fill />
    <span className="flex items-start justify-between gap-2 px-3 pt-2 text-sm font-semibold text-text-primary">{stageTitle(card, locale)}
      <span className="whitespace-nowrap rounded border border-border px-1 text-[10px] font-medium text-text-muted">{t(`stages.shape.${stageShape(card)}`)}</span></span>
    <span className="mt-0.5 line-clamp-2 px-3 text-[11px] leading-4 text-text-secondary">{stageLine(card, locale)}</span>
    <span className="mt-0.5 block px-3 pb-2 text-[11px] text-text-muted">
      {t('stages.marks', { count: stageMarks(card) })} · {t('stages.cameras', { count: card.cameras.length })}
    </span>
  </button>
}

/**
 * Stages in the shot library: the server's ``stage-<mold>`` cards (rooms and shape molds with marks and named
 * cameras). Picking one fetches its document (``world3d.templates.get``) so it opens like a personal template.
 */
export function Scene3DStageShelf({ workspace, query, locale, selectedId, onPick, onUse }: {
  workspace?: string
  query: string
  locale: 'en' | 'es'
  selectedId?: string
  onPick: (choice: StageChoice) => void
  onUse: (choice: StageChoice) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const grid = useRef<HTMLDivElement>(null)
  const [attempt, setAttempt] = useState(0)
  const key = `${workspace ?? ''}#${attempt}`
  // Keyed by workspace and attempt: a switch or a retry shows the loader, never the previous list or error.
  const [listed, setListed] = useState<{ key: string; cards?: World3DLibraryCard[]; error?: string } | null>(null)
  const [busy, setBusy] = useState('')
  const [openError, setOpenError] = useState('')
  useEffect(() => {
    if (!workspace) return
    const controller = new AbortController()
    listWorld3DStageCards(workspace, controller.signal)
      .then(cards => setListed({ key, cards }))
      .catch(reason => { if (!controller.signal.aborted) setListed({ key, error: reasonOf(reason) }) })
    return () => controller.abort()
  }, [workspace, key])
  if (!workspace) return <p role="status" className="p-4 text-sm text-text-secondary" data-testid="world3d-stages-no-workspace">{t('stages.noWorkspace')}</p>
  const current = listed?.key === key ? listed : null
  const cards = current?.cards ? filterStageCards(current.cards, query, locale) : []
  const open = (card: World3DLibraryCard, then: (choice: StageChoice) => void) => {
    setBusy(card.id); setOpenError('')
    loadStageDocument(workspace, card.id)
      .then(document => then({ card, pack: packFromStage(card, document, locale) }))
      .catch(reason => setOpenError(reasonOf(reason) === INVALID_STAGE_DOCUMENT ? t('stages.invalid') : t('stages.openError', { reason: reasonOf(reason) })))
      .finally(() => setBusy(''))
  }
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(grid.current?.querySelectorAll<HTMLButtonElement>('[data-shot-card]') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (index < 0) return
    if (event.key === 'Enter') { event.preventDefault(); open(cards[index], onUse); return }
    const columns = getComputedStyle(grid.current!).gridTemplateColumns.split(' ').filter(Boolean).length || 1
    const next = gridFocusTarget(index, event.key, buttons.length, columns)
    if (next === undefined) return
    event.preventDefault()
    buttons[next].focus()
    open(cards[next], onPick)
  }
  return <section aria-label={t('stages.title')} data-testid="world3d-stages">
    <h3 className="flex items-center gap-2 px-1 text-sm font-semibold text-text-primary">
      {t('stages.title')} <span className="text-text-muted">{current?.cards ? cards.length : ''}</span>
      {busy || (!current && workspace) ? <Loader2 size={14} className="animate-spin text-text-muted" aria-label={t('stages.loading')} /> : null}
    </h3>
    <p className="mt-1 px-1 text-xs leading-5 text-text-secondary">{t('stages.help')}</p>
    {current?.error ? <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 px-1 text-xs text-red-300">
      {t('stages.error', { reason: current.error })}
      <button type="button" onClick={() => setAttempt(value => value + 1)} className="min-h-8 rounded-lg border border-border px-3 text-text-primary hover:bg-bg-hover">{t('stages.retry')}</button>
    </div> : null}
    {openError ? <p role="alert" className="mt-2 px-1 text-xs text-red-300">{openError}</p> : null}
    {current?.cards && !current.cards.length ? <p role="status" className="p-4 text-sm text-text-secondary">{t('stages.empty')}</p> : null}
    {current?.cards?.length && !cards.length ? <p role="status" className="p-4 text-sm text-text-secondary">{t('noResults')}</p> : null}
    <div ref={grid} onKeyDown={keys} className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
      {cards.map(card => <StageCard key={card.id} card={card} workspace={workspace} locale={locale} selected={selectedId === card.id}
        onPick={() => open(card, onPick)} onUse={() => open(card, onUse)} />)}
    </div>
  </section>
}
