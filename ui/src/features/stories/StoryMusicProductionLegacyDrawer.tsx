import { ChevronRight, Film, Loader2, Music, Sparkles, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input } from './storyLabChrome'
import { ACE_STEP_MUSIC_MODEL, MINIMAX_MUSIC3_LOCAL_MODEL, clampStoryMusicDuration, isAceStepMusicModel, isLocalMusicModel, normalizeStoryMusicModel, storyMusicDurationMax, storyMusicGenerationReady } from './musicModel'
import { musicCandidateDisplayName, storySongBrief } from './storyLabMusic'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryMusicProductionLegacyDrawer(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, productionBusy, musicCoverRef, uploadCoverReference, writeStorySong, adaptStoryLyrics,
    generateMinimaxSongs, minimaxConfigured, workspace, openMusicalTrailer, storyVideoConfigurationReady,
  } = props
  return (
    <div className="hidden" aria-hidden="true">
      <Music size={26} className="text-pink-400" />
      <h3 className="font-semibold text-text-primary">{t('productions.hiddenTrailerTitle')}</h3>
      <p className="text-xs text-text-muted">{t('productions.hiddenTrailerHint')}</p>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[10px] text-text-muted">{t('productions.generationMode')}
          <select className={`${input} mt-1`} value={project.music.mode}
            onChange={event => patch({ music: { ...project.music, mode: event.target.value === 'cover' ? 'cover' : 'original' } })}>
            <option value="original">{t('music.originalSong')}</option>
            <option value="cover">{t('productions.coverFromReference')}</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">{t('productions.songModel')}
          <select className={`${input} mt-1`} value={project.music.mode === 'cover' ? 'music-cover' : project.music.model}
            disabled={project.music.mode === 'cover'}
            onChange={event => patch({ music: { ...project.music, model: normalizeStoryMusicModel(event.target.value) } })}>
            {project.music.mode === 'cover'
              ? <option value="music-cover">{t('productions.minimaxCover')}</option>
              : <>
                <option value={ACE_STEP_MUSIC_MODEL}>{t('music.aceStepDefault')}</option>
                <option value={MINIMAX_MUSIC3_LOCAL_MODEL}>{t('music.music30Local')}</option>
                <option value="music-3.0">{t('music.music30Unavailable')}</option>
                <option value="music-2.6">{t('music.music26')}</option>
              </>}
          </select>
        </label>
      </div>
      {project.music.mode === 'cover' && (
        <div className="space-y-1.5 rounded-md border border-pink-500/30 bg-pink-500/5 p-2">
          <input ref={musicCoverRef} type="file" accept="audio/*" className="hidden"
            onChange={event => void uploadCoverReference(event.target.files?.[0])} />
          <button className={`${button} w-full`} disabled={productionBusy === 'music'}
            onClick={() => musicCoverRef.current?.click()}>
            <Upload size={13} /> {project.music.coverReferenceName ? t('productions.replaceCover') : t('productions.uploadCover')}
          </button>
          {project.music.coverReferenceName && <p className="text-[9px] text-pink-200">{t('productions.referenceName', { name: project.music.coverReferenceName })}</p>}
          <p className="text-[9px] text-text-muted">{t('productions.coverLimits')}</p>
        </div>
      )}
      <textarea className={input} rows={6} value={project.music.brief || storySongBrief(project, project.music.targetDurationSeconds)}
        onChange={event => patch({ music: { ...project.music, brief: event.target.value } })}
        aria-label={t('productions.songBriefAria')} />
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[10px] text-text-muted">{t('productions.approxDuration')}
          <input className={`${input} mt-1`} type="number" min={20} max={storyMusicDurationMax(project.music.model)} step={5}
            value={project.music.targetDurationSeconds}
            onChange={event => patch({ music: { ...project.music, targetDurationSeconds: clampStoryMusicDuration(event.target.value, project.music.model) } })} />
        </label>
        <label className="block text-[10px] text-text-muted">{t('productions.candidates')}
          <select className={`${input} mt-1`} value={project.music.candidateCount}
            onChange={event => patch({ music: { ...project.music, candidateCount: Number(event.target.value) === 3 ? 3 : 2 } })}>
            <option value={2}>{t('productions.songsCount', { count: 2 })}</option>
            <option value={3}>{t('productions.songsCount', { count: 3 })}</option>
          </select>
        </label>
      </div>
      <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => void writeStorySong()}>
        {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('productions.writeSongPrompt')}
      </button>
      <div className="space-y-1.5 rounded-md border border-border p-2">
        <textarea className={input} rows={6} value={project.music.sourceLyrics}
          placeholder={t('productions.sourceLyricsPlaceholder')}
          onChange={event => patch({ music: { ...project.music, sourceLyrics: event.target.value } })}
          aria-label={t('productions.sourceLyricsAria')} />
        <button className={`${button} w-full`} disabled={productionBusy === 'music' || !project.music.sourceLyrics.trim()}
          onClick={() => void adaptStoryLyrics()}>
          <Sparkles size={13} /> {t('productions.adaptLyricsAuto')}
        </button>
        <p className="text-[9px] text-text-muted">{t('productions.adaptLyricsHint')}</p>
      </div>
      {project.music.style && (
        <textarea className={input} rows={3} value={project.music.style}
          onChange={event => patch({ music: { ...project.music, style: event.target.value } })}
          aria-label={t('productions.stylePromptAria')} />
      )}
      {project.music.lyrics && (
        <textarea className={input} rows={8} value={project.music.lyrics}
          onChange={event => patch({ music: { ...project.music, lyrics: event.target.value } })}
          aria-label={t('productions.lyricsAria')} />
      )}
      <button className={`${button} ${completeGenerationButton} w-full`}
        disabled={productionBusy === 'music' || !storyMusicGenerationReady(project.music.model, minimaxConfigured)}
        onClick={() => void generateMinimaxSongs()}>
        {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />}
        {project.music.mode === 'cover'
          ? t('productions.generateCovers', { count: project.music.candidateCount })
          : isAceStepMusicModel(project.music.model)
            ? t('productions.generateAce', { count: project.music.candidateCount })
            : project.music.model === 'music-2.6'
              ? t('productions.generate26', { count: project.music.candidateCount })
              : t('productions.generate30', { count: project.music.candidateCount })}
      </button>
      {!minimaxConfigured && !isLocalMusicModel(project.music.model) && <p className="text-[9px] text-amber-300">{t('productions.configureMinimaxCandidates')}</p>}
      <p className="text-[9px] text-text-muted">{t('productions.optionalAce')}</p>
      {project.music.candidates.length > 0 && (
        <div className="space-y-2">
          {project.music.candidates.map(candidate => {
            const selected = project.music.selectedCandidateId === candidate.id
            const label = musicCandidateDisplayName(candidate, project.title || 'Story song', project.music.lyricsLanguage || project.language, project.music.candidates.indexOf(candidate) + 1)
            return (
              <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                <button type="button" onClick={() => patch({ music: { ...project.music, selectedCandidateId: candidate.id } })}
                  className="w-full flex items-center justify-between text-[10px] text-left">
                  <span className="text-text-primary">{label} · {candidate.model}</span>
                  <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : t('music.durationOnPlayback')}</span>
                </button>
                <audio src={api.getPlayableFileUrl(candidate.source, candidate.name, workspace)} controls preload="metadata" className="w-full h-8" />
                <button className={`${button} w-full ${selected ? 'border-pink-500/50 text-pink-300' : ''}`}
                  onClick={() => void openMusicalTrailer(candidate.id)} disabled={productionBusy === 'music' || !storyVideoConfigurationReady}>
                  <Film size={12} /> {t('productions.useSongInTrailer')}
                </button>
              </div>
            )
          })}
        </div>
      )}
      <button className={`${button} w-full`} onClick={() => void openMusicalTrailer()} disabled={productionBusy === 'music' || !storyVideoConfigurationReady}>
        <ChevronRight size={13} /> {t('productions.openMusicalDirector')}
      </button>
      <p className="text-[9px] text-text-muted">{t('productions.uploadedSongsHint')}</p>
    </div>
  )
}
