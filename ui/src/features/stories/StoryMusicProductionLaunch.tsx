import { ChevronRight, Loader2, Sparkles } from 'lucide-react'
import * as api from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { AudioRangeSelector } from './AudioRangeSelector'
import { button, completeGenerationButton } from './storyLabChrome'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryMusicProductionLaunch(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, selectedMusicOption, musicProductionMode, setMusicProductionMode, musicTrailerRange,
    setMusicTrailerRange, workspace, musicProductionPacing, setMusicProductionPacing, productionBusy,
    musicProductionIssues, protagonistReferenceReady, musicWritingReady, musicVideoImageReady,
    directVideoMasterReady, directReferenceVideoReady, storyVideoConfigurationReady, stageMusicVideo,
    directMusicVideo, directReferenceVideo,
  } = props
  return (
    <>
      <div className="grid grid-cols-2 gap-1.5">
        <button type="button" onClick={() => setMusicProductionMode('full')}
          className={`${button} flex-col ${musicProductionMode === 'full' ? 'border-pink-500/60 text-pink-300' : ''}`}>
          <span>{t('productions.completeMusicVideo')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.usesEntireSong')}</span>
        </button>
        <button type="button" onClick={() => setMusicProductionMode('trailer')}
          className={`${button} flex-col ${musicProductionMode === 'trailer' ? 'border-pink-500/60 text-pink-300' : ''}`}>
          <span>{t('productions.musicalTrailer')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.usesExcerpt')}</span>
        </button>
      </div>
      {musicProductionMode === 'trailer' && selectedMusicOption && (
        <AudioRangeSelector
          key={selectedMusicOption.candidate.id}
          src={api.getPlayableFileUrl(selectedMusicOption.candidate.source, selectedMusicOption.candidate.name, workspace)}
          durationHint={selectedMusicOption.candidate.durationSeconds}
          start={musicTrailerRange.start}
          end={musicTrailerRange.end}
          onChange={setMusicTrailerRange}
        />
      )}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[10px] text-text-muted">{t('productions.editingRhythm')}</span>
          <span className="text-[9px] text-text-muted">{t('productions.balancedRecommended')}</span>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {([
            ['cinematic', 'productions.pacingCinematic', '8–16s'],
            ['balanced', 'productions.pacingBalanced', '5–8s'],
            ['rhythmic', 'productions.pacingRhythmic', '3–5s'],
          ] as const).map(([value, labelKey, duration]) => (
            <button key={value} type="button" onClick={() => setMusicProductionPacing(value)}
              className={`${button} flex-col ${musicProductionPacing === value ? 'border-pink-500/60 text-pink-300' : ''}`}>
              <span>{t(labelKey)}</span><span className="text-[9px] text-text-muted">{duration}</span>
            </button>
          ))}
        </div>
      </div>
      <label className="flex items-start gap-2 rounded-md border border-border bg-bg-tertiary/40 p-2.5 cursor-pointer">
        <input type="checkbox" checked={project.allowClipText} onChange={event => patch({ allowClipText: event.target.checked })} className="mt-0.5 accent-pink-400" />
        <span>
          <span className="block text-[10px] font-medium text-text-secondary">{t('productions.allowClipText')}</span>
          <span className="block text-[9px] leading-relaxed text-text-muted">{t('productions.allowClipTextHint')}</span>
        </span>
      </label>
      <div className="grid gap-2 sm:grid-cols-2">
        <button className={`${button} ${completeGenerationButton} w-full`}
          disabled={Boolean(productionBusy) || Boolean(musicProductionIssues.length) || !protagonistReferenceReady || !musicWritingReady || !musicVideoImageReady || !directVideoMasterReady || !directReferenceVideoReady || !storyVideoConfigurationReady}
          onClick={() => void stageMusicVideo(true)}>
          {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {musicProductionMode === 'trailer' ? t('productions.generateMusicalTrailer') : t('productions.generateCompleteMusicVideo')}
        </button>
        <button className={`${button} w-full`}
          disabled={Boolean(productionBusy) || Boolean(musicProductionIssues.length) || !protagonistReferenceReady || !musicWritingReady || !musicVideoImageReady || !directVideoMasterReady || !directReferenceVideoReady || !storyVideoConfigurationReady}
          onClick={() => void stageMusicVideo(false)}>
          <ChevronRight size={13} /> {musicProductionMode === 'trailer' ? t('productions.openTrailerDirector') : t('productions.openMusicVideoDirector')}
        </button>
      </div>
      <p className="text-[9px] text-text-muted">
        {directMusicVideo ? t('productions.saveT2v') : directReferenceVideo ? t('productions.saveRefs') : t('productions.saveImages')}
      </p>
    </>
  )
}
