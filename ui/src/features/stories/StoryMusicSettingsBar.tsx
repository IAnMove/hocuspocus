import { Loader2, Palette, RefreshCcw } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, input, panel } from './storyLabChrome'
import { ACE_STEP_MUSIC_MODEL, MINIMAX_MUSIC3_LOCAL_MODEL, isLocalMusicModel, normalizeStoryMusicModel } from './musicModel'
import type { StoryMusicTabProps } from './StoryMusicTab'
import { useStore } from '../../stores/useStore'
import { modelRequirementsText } from '../../lib/minimaxMusicCatalog'

export function StoryMusicSettingsBar(props: StoryMusicTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, busy, musicQueue, musicCueBusy, musicWritingReady, minimaxConfigured,
    createAllMusicCueVersions, musicVersionStyle, setMusicVersionStyle, musicVersionLanguage, setMusicVersionLanguage,
  } = props
  const selectedModel = useStore(state => state.models.find(model => model.model_type === project.music.model))
  const resourceHint = modelRequirementsText(selectedModel?.resource_requirements)
    || (project.music.model === MINIMAX_MUSIC3_LOCAL_MODEL ? '≈24 GB VRAM · ~28 GB en disco · CUDA' : '')
  const musicBusy = Boolean(busy || musicQueue || musicCueBusy)
  return (
    <>
      <div className={`${panel} mb-4 grid md:grid-cols-[1fr_1fr_2fr] gap-3 items-end`}>
        <label className="block text-[10px] text-text-muted">{t('music.songModel')}
          <select className={`${input} mt-1`} value={project.music.model} title={resourceHint || undefined}
            onChange={event => patch({ music: { ...project.music, model: normalizeStoryMusicModel(event.target.value) } })}>
            <option value={ACE_STEP_MUSIC_MODEL}>{t('music.aceStepDefault')}</option>
            <option value={MINIMAX_MUSIC3_LOCAL_MODEL}>{t('music.music30Local')}</option>
            <option value="music-3.0">{t('music.music30Unavailable')}</option>
            <option value="music-2.6">{t('music.music26')}</option>
          </select>
          {resourceHint && <span className="mt-1 block text-[9px] text-text-muted" title={resourceHint}>{resourceHint}</span>}
        </label>
        <div className="text-[10px] text-text-muted">{t('music.oneResultHint')}</div>
        <div className={`rounded-md border px-3 py-2 text-[10px] ${minimaxConfigured || isLocalMusicModel(project.music.model) ? 'border-emerald-500/30 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
          {isLocalMusicModel(project.music.model)
            ? t('music.minimaxLocalReady')
            : minimaxConfigured ? t('music.minimaxReady') : t('music.minimaxMissing')}
        </div>
      </div>

      <div className={`${panel} mb-4 border-purple-500/30 bg-purple-500/5`}>
        <div className="mb-2 flex items-start gap-2">
          <Palette size={17} className="mt-0.5 shrink-0 text-purple-300" />
          <div>
            <h3 className="text-xs font-semibold text-purple-200">{t('music.rewriteAllTitle')}</h3>
            <p className="mt-0.5 text-[9px] text-text-muted">{t('music.rewriteAllHint')}</p>
          </div>
        </div>
        <div className="grid md:grid-cols-[1fr_0.7fr_auto] gap-2 items-end">
          <label className="block text-[10px] text-text-muted">{t('music.newStyleOptional')}
            <input className={`${input} mt-1`} value={musicVersionStyle.all || ''}
              onChange={event => setMusicVersionStyle(current => ({ ...current, all: event.target.value }))}
              placeholder={t('music.newStylePlaceholder')} />
          </label>
          <label className="block text-[10px] text-text-muted">{t('music.newLanguageOptional')}
            <input className={`${input} mt-1`} value={musicVersionLanguage.all || ''}
              onChange={event => setMusicVersionLanguage(current => ({ ...current, all: event.target.value }))}
              placeholder={t('music.newLanguagePlaceholder')} />
          </label>
          <button className={`${button} border-purple-500/60 text-purple-200`}
            disabled={musicBusy || !musicWritingReady || !project.music.cues.length}
            onClick={() => void createAllMusicCueVersions()}>
            {musicCueBusy === 'version:all' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
            {t('music.rewriteAllDrafts')}
          </button>
        </div>
      </div>
    </>
  )
}
