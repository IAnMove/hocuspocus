import { Loader2, Music, RefreshCcw, Sparkles, Trash2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { storyMusicGenerationReady } from './musicModel'
import { button, completeGenerationButton, input } from './storyLabChrome'
import type { StoryMusicTabProps } from './StoryMusicTab'

export function StoryMusicHeader(props: StoryMusicTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, instruction, setInstruction, busy, musicQueue, musicCueBusy, newSongAction,
    musicWritingReady, minimaxConfigured, generate, generateAllMusicCues, cancelMusicQueue,
    createNewMusicVideoSong, onImportCustomMp3,
  } = props
  const musicBusy = Boolean(busy || musicQueue || musicCueBusy)
  return (
    <>
      <div id="story-review-music" className="flex flex-col xl:flex-row xl:items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">{t('music.title')}</h2>
          <p className="text-xs text-text-muted mt-1">
            {project.projectType === 'music_video' ? t('music.descriptionVideo') : t('music.descriptionStory')}
          </p>
        </div>
        <div className="flex flex-col sm:flex-row gap-2 xl:max-w-[920px]">
          <input className={`${input} sm:w-72`} value={instruction}
            onChange={event => setInstruction(event.target.value)}
            placeholder={t('music.directionPlaceholder')} />
          {project.projectType === 'music_video' ? <>
            <button className={`${button} border-violet-400/60 bg-violet-500/10 text-violet-200`}
              disabled={musicBusy || !musicWritingReady}
              onClick={() => void createNewMusicVideoSong(false)}>
              {newSongAction === 'prompts' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
              {t('music.newSongPrompts')}
            </button>
            <button className={`${button} ${completeGenerationButton}`}
              disabled={musicBusy || !musicWritingReady || !storyMusicGenerationReady(project.music.model, minimaxConfigured)}
              onClick={() => void createNewMusicVideoSong(true)}
              title={storyMusicGenerationReady(project.music.model, minimaxConfigured) ? t('music.newSongAudioTitle') : t('music.minimaxKeyTitle')}>
              {newSongAction === 'audio' ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />}
              {t('music.newSongAudio')}
            </button>
            <button className={button} disabled={musicBusy} onClick={() => {
              onImportCustomMp3(project.music.cues.find(cue => cue.kind === 'story')?.id || '')
            }}>
              <Upload size={13} /> {t('music.importCustomMp3')}
            </button>
          </> : <>
            <button className={button} disabled={Boolean(busy || musicQueue)} onClick={() => generate('music')}>
              {busy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('music.generateLlm')}
            </button>
            {musicQueue ? (
              <button className={`${button} border-red-400/60 text-red-300`} onClick={cancelMusicQueue} disabled={musicQueue.cancelling === true}>
                {musicQueue.cancelling ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                {musicQueue.cancelling ? t('music.cancellingRequest') : t('music.cancelQueue', { current: musicQueue.index + 1, total: musicQueue.ids.length })}
              </button>
            ) : (
              <button className={`${button} ${completeGenerationButton}`}
                disabled={Boolean(busy || musicCueBusy) || !project.music.cues.length || !storyMusicGenerationReady(project.music.model, minimaxConfigured)}
                onClick={() => void generateAllMusicCues()}>
                <Music size={13} /> {t('music.generateAll')}
              </button>
            )}
          </>}
        </div>
      </div>
      {project.projectType === 'music_video' && (
        <p className="-mt-2 mb-4 text-right text-[9px] text-text-muted">{t('music.newSongHint')}</p>
      )}
    </>
  )
}
