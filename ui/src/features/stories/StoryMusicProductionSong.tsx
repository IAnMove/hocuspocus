import * as api from '../../api/client'
import { getOutputReference } from '../../lib/outputReference'
import { useUiTranslation } from '../../i18n'
import { input } from './storyLabChrome'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryMusicProductionSong(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    musicCandidateOptions, musicProductionCandidateId, setMusicProductionCandidateId, selectedMusicOption, workspace,
  } = props
  return (
    <>
      <label className="block text-[10px] text-text-muted">{t('productions.song')}
        <select className={`${input} mt-1`} value={musicProductionCandidateId} onChange={event => setMusicProductionCandidateId(event.target.value)}>
          {musicCandidateOptions.map(option => (
            <option key={option.candidate.id} value={option.candidate.id}>
              {option.label} · {option.candidate.durationSeconds
                ? `${Math.floor(option.candidate.durationSeconds / 60)}:${Math.round(option.candidate.durationSeconds % 60).toString().padStart(2, '0')}`
                : t('music.durationOnPlayback')}
            </option>
          ))}
        </select>
      </label>
      {selectedMusicOption && (
        <div className="rounded-lg border border-pink-500/25 bg-pink-500/5 p-2.5 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
            <span className="font-medium text-pink-200">
              {selectedMusicOption.cue
                ? selectedMusicOption.cue.kind === 'character'
                  ? t('productions.characterFocus', { title: selectedMusicOption.cue.title })
                  : selectedMusicOption.cue.kind === 'world'
                    ? t('productions.worldFocus', { title: selectedMusicOption.cue.title })
                    : t('productions.storyFocus', { title: selectedMusicOption.cue.title })
                : t('productions.storyWideFocus')}
            </span>
            <span className="text-text-muted">
              {getOutputReference({ name: selectedMusicOption.candidate.name, type: 'audio' })} · {selectedMusicOption.candidate.provider}/{selectedMusicOption.candidate.model}
            </span>
          </div>
          {selectedMusicOption.cue?.purpose && (
            <p className="text-[10px] text-text-secondary">{selectedMusicOption.cue.purpose}</p>
          )}
          <audio src={api.getPlayableFileUrl(selectedMusicOption.candidate.source, selectedMusicOption.candidate.name, workspace)} controls preload="metadata" className="h-8 w-full" />
        </div>
      )}
    </>
  )
}
