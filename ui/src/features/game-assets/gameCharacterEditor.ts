import { fetchCharacterKitLibrary } from '../../api/characters'
import { createCharacterKit, type CharacterKit } from '../../lib/characterKit'
import { randomUuid } from '../../lib/uuid'
import { useStore } from '../../stores/useStore'
import { characterEditorHasUnsavedChanges, useCharacterEditorHandoff, type CharacterEditorRequest } from '../characters/characterEditorHandoff'
import { GameCodeError, gameText } from './gameErrors'
import { useGameAssetsStore } from './store'
import type { Game, GameAsset } from './types'

function characterOf(game: Game | null, assetId: string): GameAsset | undefined {
  return game?.assets.find(item => item.id === assetId && item.kind === 'character')
}

async function kitFor(workspace: string, asset: GameAsset): Promise<CharacterKit> {
  const library = await fetchCharacterKitLibrary(workspace)
  const kitId = typeof asset.spec.kitId === 'string' ? asset.spec.kitId : ''
  if (!kitId) return { ...createCharacterKit(asset.name), id: randomUuid() }
  if (!library.kits[kitId]) throw new GameCodeError('missing_kit')
  return { ...library.kits[kitId] }
}

/** The editor keeps a request with unsaved work for another subject; that one must finish first. */
function pendingFor(sourceId: string): CharacterEditorRequest | null {
  const pending = useCharacterEditorHandoff.getState().request
  if (!pending || pending.sourceId === sourceId) return pending
  if (characterEditorHasUnsavedChanges(pending)) throw new GameCodeError('editor_busy')
  return null
}

function showStudio(filter: 'characters' | 'gameAssets'): void {
  useStore.getState().setSettingsOpen(false)
  useStore.getState().setDashboardOpen(false)
  useStore.getState().setMediaFilter(filter)
}

export async function openGameCharacterEditor(assetId: string): Promise<void> {
  const store = useGameAssetsStore.getState()
  if (!characterOf(store.game, assetId)) throw new GameCodeError('missing_character')
  if (!(await store.saveNow())) return // the save error is already shown
  const current = useGameAssetsStore.getState()
  const fresh = characterOf(current.game, assetId)
  if (!current.game || !fresh || current.workspace !== store.workspace) throw new GameCodeError('missing_character')
  const kit = await kitFor(current.workspace, fresh)
  const sourceId = `${current.workspace}/${current.game.id}/${fresh.id}`
  const pending = pendingFor(sourceId)
  useCharacterEditorHandoff.setState({
    request: pending ?? {
      workspace: current.workspace,
      kit,
      sourceId,
      sourceLabel: `${current.game.title} · ${fresh.name}`,
      onSaved: async saved => {
        const linked = await useGameAssetsStore.getState().linkKit(assetId, saved.id)
        if (!linked) throw new Error(useGameAssetsStore.getState().error || gameText('actions.linkKit'))
      },
      onReturn: async () => showStudio('gameAssets'),
    },
  })
  showStudio('characters')
}
