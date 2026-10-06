import { useEffect } from 'react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { GameCastPanel } from './GameCastPanel'
import { GameSetupPanel } from './GameSetupPanel'
import { GameStylePanel } from './GameStylePanel'
import { buttonClass, waitingApprovals } from './styles'
import { useGameAssetsStore } from './store'
import { GAME_SECTIONS, LATER_SECTIONS } from './types'

export function GameAssetsPanel() {
  const { t } = useUiTranslation('gameAssets')
  const workspace = useStore(state => state.activeWorkspace)
  const ready = useGameAssetsStore(state => state.ready)
  const storedWorkspace = useGameAssetsStore(state => state.workspace)
  const games = useGameAssetsStore(state => state.games)
  const game = useGameAssetsStore(state => state.game)
  const section = useGameAssetsStore(state => state.section)
  const error = useGameAssetsStore(state => state.error)
  const notice = useGameAssetsStore(state => state.notice)
  const load = useGameAssetsStore(state => state.load)
  const openGame = useGameAssetsStore(state => state.openGame)
  const setSection = useGameAssetsStore(state => state.setSection)
  const createGame = useGameAssetsStore(state => state.createGame)
  const duplicateGame = useGameAssetsStore(state => state.duplicateGame)
  const deleteGame = useGameAssetsStore(state => state.deleteGame)

  useEffect(() => {
    if (ready && storedWorkspace === workspace) return
    void load(workspace)
  }, [load, ready, storedWorkspace, workspace])

  const waiting = game ? waitingApprovals(game) : []
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 md:flex-row">
      <aside className="w-full shrink-0 space-y-2 md:w-56">
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} onClick={() => { void createGame() }}>{t('new')}</button>
          <button type="button" className={buttonClass} disabled={!game} onClick={() => { void duplicateGame() }}>{t('duplicate')}</button>
          <button type="button" className={buttonClass} disabled={!game} onClick={() => { if (window.confirm(t('confirmDelete'))) void deleteGame() }}>{t('delete')}</button>
        </div>
        <ul className="max-h-48 space-y-1 overflow-y-auto md:max-h-none">
          {games.map(item => (
            <li key={item.id}>
              <button type="button" className={`${buttonClass} w-full text-left ${item.id === game?.id ? 'bg-muted' : ''}`} onClick={() => { void openGame(item.id) }}>{item.title}</button>
            </li>
          ))}
        </ul>
        {!games.length && <p className="text-sm text-muted-foreground">{t('empty')}</p>}
      </aside>
      <section className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {error && <p className="mb-2 text-sm text-red-500">{error}</p>}
        {notice === 'revision_conflict' && <p className="mb-2 text-sm">{t('conflict')}</p>}
        {game && game.style.approval !== 'approved' && <p className="mb-2 text-sm">{t('approveStyleFirst')}</p>}
        {waiting.map(item => <p key={item.id} className="mb-2 text-sm">{t('waiting', { count: item.count, name: item.name })}</p>)}
        <div className="mb-3 flex flex-wrap gap-1" role="tablist">
          {GAME_SECTIONS.map(item => (
            <button key={item} type="button" role="tab" aria-selected={section === item} className={buttonClass} onClick={() => setSection(item)}>{t(`tabs.${item}`)}</button>
          ))}
        </div>
        {game && section === 'setup' && <GameSetupPanel />}
        {game && section === 'style' && <GameStylePanel />}
        {game && section === 'cast' && <GameCastPanel />}
        {game && LATER_SECTIONS.includes(section) && <p className="text-sm text-muted-foreground">{t('soon')}</p>}
      </section>
    </div>
  )
}
