import { useUiTranslation } from '../../i18n'
import { NumberField } from './gameUi'
import { fieldClass, panelClass } from './styles'
import { useGameAssetsStore } from './store'
import type { GameGenre, GameView } from './types'

export function GameSetupPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const patchGame = useGameAssetsStore(state => state.patchGame)
  if (!game) return null
  return (
    <div className={`${panelClass} space-y-3`}>
      <label className="block text-sm">
        {t('title')}
        <input className={fieldClass} value={game.title} onChange={event => patchGame({ title: event.target.value })} />
      </label>
      <label className="block text-sm">
        {t('genre')}
        <select aria-label={t('genre')} className={fieldClass} value={game.genre} onChange={event => patchGame({ genre: event.target.value as GameGenre })}>
          <option value="platformer">{t('genres.platformer')}</option>
          <option value="topdown">{t('genres.topdown')}</option>
          <option value="other">{t('genres.other')}</option>
        </select>
      </label>
      <label className="block text-sm">
        {t('view')}
        <select aria-label={t('view')} className={fieldClass} value={game.view} onChange={event => patchGame({ view: event.target.value as GameView })}>
          <option value="side">{t('views.side')}</option>
          <option value="topdown">{t('views.topdown')}</option>
        </select>
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <NumberField label={t('tile')} min={1} value={game.style.pixel.tile} onValue={tile => patchGame({ style: { pixel: { tile } } })} />
        <NumberField label={t('spriteHeight')} min={1} value={game.style.pixel.spriteHeight}
          onValue={spriteHeight => patchGame({ style: { pixel: { spriteHeight } } })} />
      </div>
    </div>
  )
}
