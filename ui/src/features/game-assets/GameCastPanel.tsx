import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel } from './gameErrors'
import { openGameCharacterEditor } from './gameCharacterEditor'
import { assetImage, buttonClass, fieldClass, panelClass } from './styles'
import { useGameAssetsStore } from './store'

export function GameCastPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const workspace = useGameAssetsStore(state => state.workspace)
  const addCharacter = useGameAssetsStore(state => state.addCharacter)
  const showError = useGameAssetsStore(state => state.showError)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  if (!game) return null
  const characters = game.assets.filter(asset => asset.kind === 'character')

  // The name stays in the field until the server has the character.
  const submit = async () => {
    const wanted = name.trim()
    if (!wanted || busy) return
    setBusy(true)
    try {
      if (await addCharacter(wanted)) setName('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <form className={`${panelClass} flex flex-wrap items-end gap-2`} onSubmit={event => { event.preventDefault(); void submit() }}>
        <label className="block text-sm">
          {t('characterName')}
          <input className={fieldClass} value={name} onChange={event => setName(event.target.value)} />
        </label>
        <button type="submit" className={buttonClass} disabled={busy || !name.trim()}>{t('newCharacter')}</button>
      </form>
      {!characters.length && <p className="text-sm text-muted-foreground">{t('castEmpty')}</p>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {characters.map(asset => {
          const image = assetImage(asset, workspace)
          return (
            <li key={asset.id} className={panelClass}>
              {image && <img src={image} alt="" className="mb-2 h-24 w-24 object-contain" style={{ imageRendering: game.style.pixel.enabled ? 'pixelated' : 'auto' }} />}
              <p className="text-sm font-medium">{asset.name}</p>
              <p className="text-xs text-muted-foreground">{t('status')}: {codeLabel('statuses', asset.status)}</p>
              <button type="button" className={`${buttonClass} mt-2`} aria-label={t('openCreatorFor', { name: asset.name })}
                onClick={() => { openGameCharacterEditor(asset.id).catch(error => showError(error, 'openEditor')) }}>{t('openCreator')}</button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
