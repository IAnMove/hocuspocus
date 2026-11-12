import { create } from 'zustand'
import { fetchCharacterKitLibrary } from '../../api/characters'
import { useStore } from '../../stores/useStore'
import { characterEditorHasUnsavedChanges, useCharacterEditorHandoff } from '../characters/characterEditorHandoff'
import { useSeriesStore } from './store'
import { seriesCharacterKit } from './seriesCharacterKit'
import i18n from '../../i18n'

/** Where the editor was opened from; `shotId`: a shot open in the Validation tab's inspector, where it returns. */
type Source = { workspace: string; seriesId: string; characterId: string; episodeId: string; shotId?: string }
export const useSeriesCharacterReturn = create<{ source: Source | null }>(() => ({ source: null }))

function sourceCharacter(source: Source) {
  const store = useSeriesStore.getState()
  if (useStore.getState().activeWorkspace !== source.workspace || store.workspace !== source.workspace || store.activeSeriesId !== source.seriesId) {
    throw new Error(i18n.t('seriesLab:referenceBatch.sourceChanged'))
  }
  const series = store.library.seriesById[source.seriesId]
  const character = series?.characters.find(item => item.id === source.characterId)
  if (!character) throw new Error(i18n.t('seriesLab:speech.missingLink'))
  return { series, character }
}

/** The pose to open, when the kit has it. */
function kitPose(kit: ReturnType<typeof seriesCharacterKit>, poseId?: string) {
  return poseId === 'base' || (poseId && kit.poses[poseId]) ? poseId : undefined
}

/** Open a series character's Character Kit in the Characters tool; with `poseId` its speech workshop opens on that pose's
 * mouth / face rig (the pose a shot uses). */
export async function openSeriesCharacterEditor(workspace: string, seriesId: string, characterId: string, options: { poseId?: string; shotId?: string } = {}) {
  const source: Source = { workspace, seriesId, characterId, episodeId: useSeriesStore.getState().activeEpisodeId, ...(options.shotId ? { shotId: options.shotId } : {}) }
  sourceCharacter(source)
  await useSeriesStore.getState().saveNow()
  const library = await fetchCharacterKitLibrary(workspace)
  const { series, character } = sourceCharacter(source)
  const ref = character.voiceProfile?.characterKitRef
  if (ref && (ref.workspace !== workspace || !library.kits[ref.id])) throw new Error(i18n.t('seriesLab:speech.missingLink'))
  const kit = seriesCharacterKit(workspace, series, character, ref ? library.kits[ref.id] : undefined)
  const sourceId = `${workspace}/${seriesId}/${characterId}`
  let pending = useCharacterEditorHandoff.getState().request
  if (pending && pending.sourceId !== sourceId && !characterEditorHasUnsavedChanges(pending)) pending = null
  if (pending && pending.sourceId !== sourceId) {
    throw new Error(i18n.t('seriesLab:speech.finishEditor'))
  }
  const poseId = kitPose(kit, options.poseId)
  useCharacterEditorHandoff.setState({ request: pending ? { ...pending, poseId } : {
    workspace, kit, sourceId, sourceLabel: `${series.title} · ${character.name}`, poseId,
    onSaved: async saved => {
      const current = sourceCharacter(source).character.voiceProfile?.characterKitRef
      if (current && (current.workspace !== workspace || (current.id !== ref?.id && current.id !== saved.id))) throw new Error(i18n.t('seriesLab:speech.changedLink'))
      useSeriesStore.getState().updateSeries(value => ({ ...value, characters: value.characters.map(item => item.id === characterId
        ? { ...item, voiceProfile: { ...item.voiceProfile, characterKitRef: { workspace, id: saved.id } } } : item) }))
      await useSeriesStore.getState().saveNow()
    },
    onReturn: async () => {
      if (useStore.getState().activeWorkspace !== workspace) throw new Error(i18n.t('seriesLab:referenceBatch.sourceChanged'))
      await useSeriesStore.getState().openSeries(seriesId)
      sourceCharacter(source)
      useSeriesStore.getState().openEpisode(source.episodeId)
      useSeriesCharacterReturn.setState({ source })
      useStore.getState().setMediaFilter('series')
    },
  } })
  useStore.getState().setSettingsOpen(false)
  useStore.getState().setDashboardOpen(false)
  useStore.getState().setMediaFilter('characters')
}
