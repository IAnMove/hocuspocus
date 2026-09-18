import { useUiTranslation } from '../../i18n'
import { SpeechProductionEntry } from '../scene3d/speech/SpeechProductionEntry'
import { seriesShotMethod } from './productionMethods'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

export function SeriesShotSpeechEntry({ workspace, series, episode, shot, onConfigureCharacter }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot; onConfigureCharacter?: (id: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const cast = [...new Set(shot.dialogueBeats.map(beat => beat.characterId))].map(id => {
    const person = series.characters.find(character => character.id === id)
    return { id, name: person?.name || id, characterKitRef: person?.voiceProfile?.characterKitRef }
  })
  if (!cast.length) return null
  if (seriesShotMethod(series, shot) === 'animation_2d') return <div className="mt-3 space-y-2">
    <p className="text-xs text-text-secondary">{t('speech.configure')}</p>
    <div className="flex flex-wrap gap-2">{cast.map(character => <button key={character.id} className={secondaryButton}
      disabled={!onConfigureCharacter} onClick={() => onConfigureCharacter?.(character.id)}>{character.name}</button>)}</div>
  </div>
  return <SpeechProductionEntry kind="episode" workspace={workspace} onConfigureCharacter={onConfigureCharacter}
    title={`${episode.title} · ${shot.order}`} sourceId={`${series.id}/${episode.id}/${shot.id}`} cast={cast}
    lines={shot.dialogueBeats.map(beat => ({ id: beat.id, characterId: beat.characterId, text: beat.text }))} />
}
