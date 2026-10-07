import { useEffect } from 'react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { GameCastPanel } from './GameCastPanel'
import { GameListPanel } from './GameListPanel'
import { GameProducePanel } from './GameProducePanel'
import { GameReviewPanel } from './GameReviewPanel'
import { GameSetupPanel } from './GameSetupPanel'
import { GameStylePanel } from './GameStylePanel'
import { ErrorNotice } from './gameUi'
import { buttonClass, choiceClass, waitingApprovals } from './styles'
import { stopGamePolling, useGameAssetsStore, watchGameJobs } from './store'
import { GAME_SECTIONS, LATER_SECTIONS, type GameSection } from './types'

export function GameAssetsPanel() {
  const workspace = useStore(state => state.activeWorkspace)
  const load = useGameAssetsStore(state => state.load)

  useEffect(() => {
    const state = useGameAssetsStore.getState()
    if (state.workspace !== workspace || !state.ready) void load(workspace)
  }, [load, workspace])

  useEffect(() => {
    watchGameJobs()
    return () => stopGamePolling()
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 md:flex-row">
      <GameLibrary />
      <section className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <GameNotices />
        <GameTabs />
        <GameSectionBody />
      </section>
    </div>
  )
}

function GameLibrary() {
  const { t } = useUiTranslation('gameAssets')
  const ready = useGameAssetsStore(state => state.ready)
  const games = useGameAssetsStore(state => state.games)
  const game = useGameAssetsStore(state => state.game)
  const openGame = useGameAssetsStore(state => state.openGame)
  const createGame = useGameAssetsStore(state => state.createGame)
  const duplicateGame = useGameAssetsStore(state => state.duplicateGame)
  const deleteGame = useGameAssetsStore(state => state.deleteGame)
  return (
    <aside className="w-full shrink-0 space-y-2 md:w-56">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={!ready} onClick={() => { void createGame() }}>{t('new')}</button>
        <button type="button" className={buttonClass} disabled={!game} onClick={() => { void duplicateGame() }}>{t('duplicate')}</button>
        <button type="button" className={buttonClass} disabled={!game} onClick={() => { if (window.confirm(t('confirmDelete'))) void deleteGame() }}>{t('delete')}</button>
      </div>
      <ul className="max-h-48 space-y-1 overflow-y-auto md:max-h-none">
        {games.map(item => (
          <li key={item.id}>
            <button type="button" className={`${choiceClass(item.id === game?.id)} w-full text-left`} aria-current={item.id === game?.id ? 'true' : undefined}
              onClick={() => { void openGame(item.id) }}>{item.title}</button>
          </li>
        ))}
      </ul>
      {!ready && <p className="text-sm text-muted-foreground" role="status">{t('loading')}</p>}
      {ready && !games.length && <p className="text-sm text-muted-foreground">{t('empty')}</p>}
    </aside>
  )
}

function GameNotices() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const error = useGameAssetsStore(state => state.error)
  const problems = useGameAssetsStore(state => state.problems)
  const notice = useGameAssetsStore(state => state.notice)
  const waiting = game ? waitingApprovals(game) : []
  return (
    <>
      <ErrorNotice error={error} problems={problems} />
      {notice === 'revision_conflict' && <p className="mb-2 text-sm" role="status">{t('conflict')}</p>}
      {game && game.style.approval !== 'approved' && <p className="mb-2 text-sm">{t('approveStyleFirst')}</p>}
      {waiting.map(item => <p key={item.id} className="mb-2 text-sm">{t('waiting', { count: item.count, name: item.name })}</p>)}
    </>
  )
}

function GameTabs() {
  const { t } = useUiTranslation('gameAssets')
  const section = useGameAssetsStore(state => state.section)
  const setSection = useGameAssetsStore(state => state.setSection)
  return (
    <div className="mb-3 flex flex-wrap gap-1" role="tablist">
      {GAME_SECTIONS.map(item => (
        <button key={item} type="button" role="tab" aria-selected={section === item} className={choiceClass(section === item)}
          onClick={() => setSection(item)}>{t(`tabs.${item}`)}</button>
      ))}
    </div>
  )
}

function SectionPanel({ section }: { section: GameSection }) {
  switch (section) {
    case 'setup': return <GameSetupPanel />
    case 'style': return <GameStylePanel />
    case 'cast': return <GameCastPanel />
    case 'list': return <GameListPanel />
    case 'produce': return <GameProducePanel />
    case 'review': return <GameReviewPanel />
    default: return null
  }
}

function GameSectionBody() {
  const { t } = useUiTranslation('gameAssets')
  const hasGame = useGameAssetsStore(state => Boolean(state.game))
  const section = useGameAssetsStore(state => state.section)
  if (!hasGame) return null
  if (LATER_SECTIONS.includes(section)) return <p className="text-sm text-muted-foreground">{t('soon')}</p>
  return <div role="tabpanel"><SectionPanel section={section} /></div>
}
