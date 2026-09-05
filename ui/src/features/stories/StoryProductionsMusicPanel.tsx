import { Music } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { panel } from './storyLabChrome'
import { StoryMusicProductionGuide } from './StoryMusicProductionGuide'
import { StoryMusicProductionLaunch } from './StoryMusicProductionLaunch'
import { StoryMusicProductionLegacyDrawer } from './StoryMusicProductionLegacyDrawer'
import { StoryMusicProductionModels } from './StoryMusicProductionModels'
import { StoryMusicProductionSong } from './StoryMusicProductionSong'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryProductionsMusicPanel(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, musicCandidateOptions, selectedFilmVideoModel, filmVideoModel, musicWritingReady,
    musicVideoImageReady, directVideoMasterReady, directReferenceVideoReady, onNavigate,
  } = props
  const writerLabel = project.provider.writingProvider === 'maestro' ? t('productions.internalLlm') : project.provider.writingModel
  const videoLabel = selectedFilmVideoModel?.name || filmVideoModel
  const ready = musicWritingReady && musicVideoImageReady && directVideoMasterReady && directReferenceVideoReady
  return (
    <div className={`${panel} space-y-3 md:col-span-2`}>
      <div className="flex items-start gap-3">
        <Music size={26} className="shrink-0 text-pink-400" />
        <div>
          <h3 className="font-semibold text-text-primary">{t('productions.musicVideoTitle')}</h3>
          <p className="mt-1 text-xs text-text-muted">{t('productions.musicVideoHint')}</p>
        </div>
      </div>
      {musicCandidateOptions.length ? (
        <>
          <StoryMusicProductionSong {...props} />
          <StoryMusicProductionGuide {...props} />
          <StoryMusicProductionModels {...props} ready={ready} writerLabel={writerLabel} videoLabel={videoLabel} />
          <StoryMusicProductionLaunch {...props} />
        </>
      ) : (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          {t('productions.noSongs')}{' '}
          <button type="button" className="underline" onClick={() => onNavigate('music')}>{t('productions.openMusic')}</button>
          {' '}{t('productions.noSongsHint')}
        </div>
      )}
      <StoryMusicProductionLegacyDrawer {...props} />
    </div>
  )
}
