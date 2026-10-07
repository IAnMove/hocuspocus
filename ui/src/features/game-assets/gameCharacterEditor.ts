import { fetchCharacterKitLibrary } from '../../api/characters'
import { createCharacterKit } from '../../lib/characterKit'
import { randomUuid } from '../../lib/uuid'
import { useStore } from '../../stores/useStore'
import { characterEditorHasUnsavedChanges, useCharacterEditorHandoff } from '../characters/characterEditorHandoff'
import { useGameAssetsStore } from './store'

export async function openGameCharacterEditor(assetId: string): Promise<void> {
  const store = useGameAssetsStore.getState()
  const game = store.game
  const asset = game?.assets.find(item => item.id === assetId && item.kind === 'character')
  if (!game || !asset) throw new Error('Missing character')
  await store.saveNow()
  const current = useGameAssetsStore.getState()
  const fresh = current.game?.assets.find(item => item.id === assetId)
  if (!current.game || !fresh || current.workspace !== store.workspace) throw new Error('Missing character')
  const library = await fetchCharacterKitLibrary(current.workspace)
  const kitId = typeof fresh.spec.kitId === 'string' ? fresh.spec.kitId : ''
  if (kitId && !library.kits[kitId]) throw new Error('Missing character kit')
  const kit = kitId ? { ...library.kits[kitId] } : { ...createCharacterKit(fresh.name), id: randomUuid() }
  const sourceId = `${current.workspace}/${current.game.id}/${fresh.id}`
  let pending = useCharacterEditorHandoff.getState().request
  if (pending && pending.sourceId !== sourceId && !characterEditorHasUnsavedChanges(pending)) pending = null
  if (pending && pending.sourceId !== sourceId) throw new Error('Finish the character editor first')
  useCharacterEditorHandoff.setState({
    request: pending ?? {
      workspace: current.workspace,
      kit,
      sourceId,
      sourceLabel: `${current.game.title} · ${fresh.name}`,
      onSaved: async saved => {
        await useGameAssetsStore.getState().linkKit(assetId, saved.id)
      },
      onReturn: async () => {
        useStore.getState().setSettingsOpen(false)
        useStore.getState().setDashboardOpen(false)
        useStore.getState().setMediaFilter('gameAssets')
      },
    },
  })
  useStore.getState().setSettingsOpen(false)
  useStore.getState().setDashboardOpen(false)
  useStore.getState().setMediaFilter('characters')
}
