import type { ChangeEvent } from 'react'
import { ChevronDown, ChevronRight, Film, Languages, Music, Palette, RefreshCcw, Sparkles, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel, Field } from './storyLabChrome'
import { musicCandidateDisplayName, storySongBrief } from './storyLabMusic'
import { isLocalMusicModel } from './musicModel'
import type { StoryMusicTabProps } from './StoryMusicTab'

export function ManualSongPanel({
  project, patch, productionBusy, musicWritingReady, minimaxConfigured, storyVideoConfigurationReady, workspace,
  musicVersionStyle, setMusicVersionStyle, musicVersionLanguage, setMusicVersionLanguage, lyricsTranslationLanguage,
  setLyricsTranslationLanguage, openMusicalTrailer, musicCoverRef, uploadCoverReference, writeStorySong, adaptStoryLyrics,
  translateManualSongLyrics, createManualSongVersion, generateMinimaxSongs,
}: StoryMusicTabProps) {
  const { t } = useUiTranslation('storyLab')
  const onCover = (event: ChangeEvent<HTMLInputElement>) => {
    void uploadCoverReference(event.target.files?.[0])
  }
  return (
    <details className={`${panel} group`}>
      <summary className="cursor-pointer list-none flex items-center justify-between gap-2">
        <span>
          <span className="block text-sm font-semibold text-text-primary">{t('music.manualTitle')}</span>
          <span className="block text-[10px] text-text-muted mt-1">{t('music.manualHint')}</span>
        </span>
        <ChevronDown size={15} className="group-open:rotate-180 transition-transform" />
      </summary>
      <div className="mt-4 grid lg:grid-cols-2 gap-3">
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[10px] text-text-muted">{t('music.mode')}
              <select className={`${input} mt-1`} value={project.music.mode}
                onChange={event => patch({ music: { ...project.music, mode: event.target.value === 'cover' ? 'cover' : 'original' } })}>
                <option value="original">{t('music.originalSong')}</option><option value="cover">{t('music.cover')}</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">{t('music.candidates')}
              <select className={`${input} mt-1`} value={project.music.candidateCount}
                onChange={event => patch({ music: { ...project.music, candidateCount: Number(event.target.value) === 3 ? 3 : 2 } })}>
                <option value={2}>2</option><option value={3}>3</option>
              </select>
            </label>
          </div>
          {project.music.mode === 'cover' && <>
            <input ref={musicCoverRef} type="file" accept="audio/*" className="hidden" onChange={onCover} />
            <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => musicCoverRef.current?.click()}>
              <Upload size={13} /> {project.music.coverReferenceName ? t('music.replaceCover', { name: project.music.coverReferenceName }) : t('music.uploadCover')}
            </button>
          </>}
          <Field label={t('music.songBrief')} value={project.music.brief || storySongBrief(project, project.music.targetDurationSeconds)}
            onChange={brief => patch({ music: { ...project.music, brief } })} rows={5} />
          <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => void writeStorySong()}>
            <Sparkles size={13} /> {t('music.writePromptLyrics')}
          </button>
          <Field label={t('music.sourceLyrics')} value={project.music.sourceLyrics}
            onChange={sourceLyrics => patch({ music: { ...project.music, sourceLyrics } })} rows={5} />
          <button className={`${button} w-full`} disabled={productionBusy === 'music' || !project.music.sourceLyrics.trim()}
            onClick={() => void adaptStoryLyrics()}><Sparkles size={13} /> {t('music.adaptLyrics')}</button>
        </div>
        <div className="space-y-2">
          <Field required label={t('music.finalPrompt')} value={project.music.style}
            onChange={style => patch({ music: { ...project.music, style } })} rows={3} />
          <Field required label={t('music.editableLyrics')} value={project.music.lyrics}
            onChange={lyrics => patch({ music: { ...project.music, lyrics } })} rows={8} />
          <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <label className="block text-[10px] text-text-muted">{t('music.translateTo')}
              <input className={`${input} mt-1`} value={lyricsTranslationLanguage.manual || ''}
                onChange={event => setLyricsTranslationLanguage(current => ({ ...current, manual: event.target.value }))}
                placeholder={t('music.translatePlaceholder')} />
            </label>
            <button className={`${button} self-end`} disabled={productionBusy === 'music' || !musicWritingReady || !project.music.lyrics.trim()}
              onClick={() => void translateManualSongLyrics()}><Languages size={13} /> {t('music.translate')}</button>
          </div>
          <p className="text-[9px] text-text-muted">{t('music.manualTranslateHint')}</p>
          <div className="space-y-2 rounded-lg border border-purple-500/30 bg-purple-500/5 p-2.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-200"><Palette size={12} /> {t('music.manualNewVersion')}</div>
            <div className="grid sm:grid-cols-2 gap-2">
              <input className={input} value={musicVersionStyle.manual || ''}
                onChange={event => setMusicVersionStyle(current => ({ ...current, manual: event.target.value }))}
                placeholder={t('music.manualStylePlaceholder')} />
              <input className={input} value={musicVersionLanguage.manual || ''}
                onChange={event => setMusicVersionLanguage(current => ({ ...current, manual: event.target.value }))}
                placeholder={t('music.languageCurrent', { language: project.music.lyricsLanguage || project.language })} />
            </div>
            <button className={`${button} w-full border-purple-500/60 text-purple-200`}
              disabled={productionBusy === 'music' || !musicWritingReady}
              onClick={() => void createManualSongVersion()}><RefreshCcw size={13} /> {t('music.rewriteStyleLyricsShort')}</button>
            <p className="text-[9px] text-text-muted">{t('music.manualVersionHint')}</p>
          </div>
          <label className="block text-[10px] text-text-muted">{t('music.targetDuration')}
            <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
              value={project.music.targetDurationSeconds}
              onChange={event => patch({ music: { ...project.music, targetDurationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) } })} />
          </label>
          <p className="text-[9px] text-text-muted">{t('music.manualDurationHint')}</p>
          <button className={`${button} ${completeGenerationButton} w-full`}
            disabled={productionBusy === 'music' || (!minimaxConfigured && !isLocalMusicModel(project.music.model))}
            onClick={() => void generateMinimaxSongs()}><Music size={13} /> {t('music.generateManual')}</button>
          {project.music.candidates.map(candidate => (
            <div key={candidate.id} className="rounded border border-border p-2 space-y-1.5">
              <span className="text-[10px] text-text-primary">{musicCandidateDisplayName(candidate, project.title || 'Story song', project.music.lyricsLanguage || project.language, project.music.candidates.indexOf(candidate) + 1)} · {candidate.model}</span>
              <audio src={api.getPlayableFileUrl(candidate.source, candidate.name, workspace)} controls preload="metadata" className="w-full h-8" />
              <button className={`${button} w-full`} disabled={!storyVideoConfigurationReady} onClick={() => void openMusicalTrailer(candidate.id)}><Film size={12} /> {t('music.useInTrailer')}</button>
            </div>
          ))}
          <button className={`${button} w-full`} disabled={!storyVideoConfigurationReady} onClick={() => void openMusicalTrailer()}>
            <ChevronRight size={13} /> {t('music.openMusicalDirector')}
          </button>
        </div>
      </div>
    </details>
  )
}
