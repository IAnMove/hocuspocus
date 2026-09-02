import { ChevronRight, Film, Loader2, Music, RefreshCcw, Sparkles, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { getOutputReference } from '../../lib/outputReference'
import { useUiTranslation } from '../../i18n'
import { AudioRangeSelector } from './AudioRangeSelector'
import { button, completeGenerationButton, input, panel, requiredInput } from './storyLabChrome'
import { ACE_STEP_MUSIC_MODEL, isAceStepMusicModel, normalizeStoryMusicModel } from './musicModel'
import { musicCandidateDisplayName, storySongBrief } from './storyLabMusic'
import { StoryVideoFormatControls } from './StoryVideoFormatControls'
import type { StoryProductionsTabProps } from './storyLabProductions'
import type { StoryWritingProvider } from './types'

export function StoryProductionsMusicPanel(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, workspace, productionBusy, musicProductionCandidateId, setMusicProductionCandidateId,
    musicCandidateOptions, selectedMusicOption, musicProductionMode, setMusicProductionMode, musicProductionPacing,
    setMusicProductionPacing, musicTrailerRange, setMusicTrailerRange, stageMusicVideo, setMusicWritingProvider,
    patchMusicWritingProvider, directMusicVideo, directReferenceVideo, approvedVisualReferenceCount,
    directReferenceVideoReady, directReferenceVideoSupported, directVideoMasterReady, protagonistReferenceReady,
    musicWritingReady, musicVideoImageReady, filmImageModel, filmVideoModel, selectableImageModels, selectableVideoModels,
    selectedFilmImageModel, selectedFilmVideoModel, selectDirectorImageModel, selectStoryVideoModel, storyVideoOptionsReady,
    storyVideoConfigurationReady, storyVideoResolution, storyVideoAspectRatio, storyVideoOptions, storyVideoAdjusted,
    setStoryVideoFormat, musicProductionIssues, onNavigate, minimaxConfigured, musicCoverRef, uploadCoverReference,
    writeStorySong, adaptStoryLyrics, generateMinimaxSongs, openMusicalTrailer,
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
          <div className="rounded-lg border border-fuchsia-500/35 bg-fuchsia-500/5 p-2.5 space-y-2.5">
            <div>
              <p className="text-[10px] font-medium text-fuchsia-200">{t('productions.howToGenerate')}</p>
              <p className="mt-0.5 text-[9px] leading-relaxed text-text-muted">{t('productions.howToGenerateHint')}</p>
            </div>
            <div className="grid gap-1.5 md:grid-cols-3">
              <button type="button" onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}
                className={`${button} flex-col ${project.musicVideoGenerationMode === 'image_guided' ? 'border-pink-500/60 text-pink-300' : ''}`}>
                <span>{t('productions.withImages')}</span>
                <span className="text-[9px] text-text-muted">{t('productions.withImagesHint')}</span>
              </button>
              <button type="button" onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}
                className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`}>
                <span>{t('productions.directWithRefs')}</span>
                <span className="text-[9px] text-text-muted">{t('productions.h3NoStart')}</span>
              </button>
              <button type="button" disabled={project.protagonistConsistency} onClick={() => patch({ musicVideoGenerationMode: 'direct_video' })}
                className={`${button} flex-col ${directMusicVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`}>
                <span>{t('productions.directVideoNoImages')}</span>
                <span className="text-[9px] text-text-muted">{t('productions.pureT2v')}</span>
              </button>
            </div>
            {project.protagonistConsistency && <p className="text-[9px] text-amber-300">{t('productions.fixedProtagonist')}</p>}
            {directReferenceVideo && (
              <div className={`rounded-md border p-2 text-[9px] leading-relaxed ${directReferenceVideoReady
                ? 'border-emerald-500/35 bg-emerald-500/5 text-emerald-100'
                : 'border-amber-500/40 bg-amber-500/5 text-amber-200'}`}>
                {directReferenceVideoReady
                  ? t('productions.refsRouted', { count: approvedVisualReferenceCount })
                  : directReferenceVideoSupported
                    ? t('productions.approveBeforeGenerate')
                    : t('productions.h3OnlyMode')}
              </div>
            )}
            {directMusicVideo && (
              <div className="block text-[10px] text-violet-200">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span>{t('productions.masterPrompt')}<span className="ml-1 text-violet-300" title={t('chrome.required')}>●</span></span>
                  <span className={`rounded-full border px-1.5 py-0.5 text-[9px] ${project.directVideoMasterPromptMode === 'inherit'
                    ? 'border-violet-400/50 bg-violet-500/10 text-violet-200'
                    : 'border-sky-400/50 bg-sky-500/10 text-sky-200'}`}>
                    {project.directVideoMasterPromptMode === 'inherit' ? t('productions.inheritedStyles') : t('productions.customPrompt')}
                  </span>
                  {project.directVideoMasterPromptMode === 'custom' && (
                    <button type="button" onClick={() => patch({ directVideoMasterPromptMode: 'inherit' })}
                      className="ml-auto inline-flex items-center gap-1 rounded border border-violet-400/45 px-1.5 py-0.5 text-[9px] text-violet-200 hover:bg-violet-500/15"
                      title={t('productions.useCurrentStylesTitle')}>
                      <RefreshCcw size={10} /> {t('productions.useCurrentStyles')}
                    </button>
                  )}
                </div>
                <textarea className={`${input} ${requiredInput} mt-1 min-h-36 resize-y leading-relaxed`}
                  value={project.directVideoMasterPrompt}
                  onChange={event => patch({ directVideoMasterPromptMode: 'custom', directVideoMasterPrompt: event.target.value })}
                  placeholder={t('productions.masterPlaceholder')} required aria-required="true" />
                <span className={`mt-1 block text-[9px] leading-relaxed ${directVideoMasterReady ? 'text-fuchsia-200/80' : 'text-amber-300'}`}>
                  {directVideoMasterReady
                    ? project.directVideoMasterPromptMode === 'inherit' ? t('productions.inheritReady') : t('productions.customReady')
                    : t('productions.completeMasterOrStyle')}
                </span>
              </div>
            )}
          </div>
          <div className="rounded-lg border border-border bg-bg-tertiary/40 p-2.5 space-y-2">
            <div>
              <p className="text-[10px] font-medium text-text-secondary">{t('productions.generationModels')}</p>
              <p className="mt-0.5 text-[9px] text-text-muted">{t('productions.generationModelsHint')}</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <label className="block text-[10px] text-text-muted">{t('productions.planningLlm')}
                <select className={`${input} mt-1`} value={project.provider.writingProvider}
                  onChange={event => setMusicWritingProvider(event.target.value as StoryWritingProvider)}>
                  <option value="maestro">{t('productions.internalLlm')}</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="minimax">MiniMax</option>
                  <option value="openai">OpenAI</option>
                  <option value="openai-compatible">Custom OpenAI-compatible</option>
                </select>
              </label>
              {project.provider.writingProvider !== 'maestro' && (
                <label className="block text-[10px] text-text-muted">{t('productions.llmModel')}
                  {project.provider.writingProvider === 'deepseek' ? (
                    <select className={`${input} mt-1`} value={project.provider.writingModel || 'deepseek-v4-pro'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                      <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                      <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
                    </select>
                  ) : project.provider.writingProvider === 'minimax' ? (
                    <select className={`${input} mt-1`} value={project.provider.writingModel || 'MiniMax-M3'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                      <option value="MiniMax-M3">MiniMax M3</option>
                      <option value="MiniMax-M2.7">MiniMax M2.7</option>
                      <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed</option>
                    </select>
                  ) : (
                    <input className={`${input} mt-1`} value={project.provider.writingModel} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })} />
                  )}
                </label>
              )}
              {directMusicVideo || directReferenceVideo ? (
                <div className="rounded-md border border-fuchsia-500/25 bg-fuchsia-500/5 px-2 py-1.5 text-[10px] text-text-muted">
                  <span className="block font-medium text-fuchsia-200">{t('productions.imageUnused')}</span>
                  <span className="mt-1 block text-[9px]">{directReferenceVideo ? t('productions.imageUnusedRefs') : t('productions.imageUnusedT2v')}</span>
                </div>
              ) : (
                <label className="block text-[10px] text-text-muted">{t('trailer.imageModel')}
                  <select className={`${input} mt-1`} value={filmImageModel} onChange={event => selectDirectorImageModel(event.target.value)}>
                    {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && (
                      <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>
                    )}
                    <optgroup label={t('productions.externalApi')}>
                      <option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option>
                    </optgroup>
                    <optgroup label={t('productions.localModels')}>
                      {selectableImageModels.map(model => (
                        <option key={model.model_type} value={model.model_type}>{model.name}</option>
                      ))}
                    </optgroup>
                  </select>
                </label>
              )}
              <label className="block text-[10px] text-text-muted">{t('trailer.videoModel')}
                <select className={`${input} mt-1`} value={filmVideoModel}
                  disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady}
                  onChange={event => selectStoryVideoModel(event.target.value)}>
                  {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && (
                    <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>
                  )}
                  {selectableVideoModels.map(model => (
                    <option key={model.model_type} value={model.model_type}>
                      {model.name}{model.is_downloaded === false ? t('productions.downloadsOnFirstUse') : ''}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">
                  {!storyVideoOptionsReady
                    ? t('productions.checkingFormats')
                    : project.provider.useGlobalProfile
                      ? t('productions.inheritedStoryOnly')
                      : filmVideoModel === 'minimax_h3_legacy'
                        ? t('productions.h3LegacyMusic')
                        : filmVideoModel.startsWith('ltx2')
                          ? t('productions.ltxGemma')
                          : t('productions.h3SavedStory')}
                </span>
              </label>
              <StoryVideoFormatControls
                videoModel={filmVideoModel}
                resolution={storyVideoResolution}
                aspectRatio={storyVideoAspectRatio}
                options={storyVideoOptions}
                disabled={!storyVideoOptionsReady}
                inherited={project.provider.useGlobalProfile}
                adjusted={storyVideoAdjusted}
                onChange={setStoryVideoFormat}
              />
            </div>
            {project.provider.writingProvider === 'openai-compatible' && (
              <label className="block text-[10px] text-text-muted">{t('productions.compatibleBaseUrl')}
                <input className={`${input} mt-1`} value={project.provider.writingBaseUrl} onChange={event => patchMusicWritingProvider({ writingBaseUrl: event.target.value })} placeholder="https://…/v1" />
              </label>
            )}
            <p className={`text-[9px] ${ready ? 'text-text-muted' : 'text-amber-300'}`}>
              {ready
                ? directMusicVideo
                  ? t('productions.readyT2v', { writer: writerLabel, video: videoLabel })
                  : directReferenceVideo
                    ? t('productions.readyRefs', { writer: writerLabel, count: approvedVisualReferenceCount, video: videoLabel })
                    : t('productions.readyImages', { writer: writerLabel, image: selectedFilmImageModel?.name || filmImageModel, video: videoLabel })
                : !musicWritingReady
                  ? t('productions.configurePlanningLlm')
                  : !directVideoMasterReady
                    ? t('productions.defineMaster')
                    : !directReferenceVideoReady
                      ? directReferenceVideoSupported
                        ? t('productions.approveLibrary')
                        : t('productions.directRefsNeedH3')
                      : t('productions.configureMinimaxImage')}
            </p>
          </div>
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
      ) : (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
          {t('productions.noSongs')}{' '}
          <button type="button" className="underline" onClick={() => onNavigate('music')}>{t('productions.openMusic')}</button>
          {' '}{t('productions.noSongsHint')}
        </div>
      )}
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
            <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
              value={project.music.targetDurationSeconds}
              onChange={event => patch({ music: { ...project.music, targetDurationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) } })} />
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
          disabled={productionBusy === 'music' || !minimaxConfigured}
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
        {!minimaxConfigured && <p className="text-[9px] text-amber-300">{t('productions.configureMinimaxCandidates')}</p>}
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
    </div>
  )
}
