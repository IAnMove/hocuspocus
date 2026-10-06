import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { openGameCharacterEditor } from './gameCharacterEditor'
import { assetImage, buttonClass, fieldClass, panelClass } from './styles'
import { useGameAssetsStore } from './store'

export function GameCastPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const workspace = useGameAssetsStore(state => state.workspace)
  const addCharacter = useGameAssetsStore(state => state.addCharacter)
  const [name, setName] = useState('')
  if (!game) return null
  const characters = game.assets.filter(asset => asset.kind === 'character')
  return (
    <div className="space-y-3">
      <form className={`${panelClass} flex flex-wrap items-end gap-2`} onSubmit={event => { event.preventDefault(); if (!name.trim()) return; void addCharacter(name.trim()); setName('') }}>
        <label className="block text-sm">
          {t('characterName')}
          <input className={fieldClass} value={name} onChange={event => setName(event.target.value)} />
        </label>
        <button type="submit" className={buttonClass}>{t('newCharacter')}</button>
      </form>
      {!characters.length && <p className="text-sm text-muted-foreground">{t('castEmpty')}</p>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {characters.map(asset => {
          const image = assetImage(asset, workspace)
          return (
            <li key={asset.id} className={panelClass}>
              {image && <img src={image} alt="" className="mb-2 h-24 w-24 object-contain" style={{ imageRendering: game.style.pixel.enabled ? 'pixelated' : 'auto' }} />}
              <p className="text-sm font-medium">{asset.name}</p>
              <p className="text-xs text-muted-foreground">{t('status')}: {asset.status}</p>
              <button type="button" className={`${buttonClass} mt-2`} onClick={() => { void openGameCharacterEditor(asset.id) }}>{t('openCreator')}</button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
