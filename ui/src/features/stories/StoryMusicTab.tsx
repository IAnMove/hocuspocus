import type { ChangeEvent, RefObject } from 'react'
import {
  ChevronDown, ChevronRight, Copy, ExternalLink, Film, Languages, Loader2, Music, Palette, RefreshCcw, Sparkles, Trash2, Upload,
} from 'lucide-react'
import * as api from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel, Field, type StoryMusicQueue } from './storyLabChrome'
import { ACE_STEP_MUSIC_MODEL, normalizeStoryMusicModel } from './musicModel'
import {
  MINIMAX_LYRIC_SECTION, miniMaxCuePayload, musicCandidateDisplayName, storySongBrief,
} from './storyLabMusic'
import type { StoryGenerationScope, StoryMusicCue, StoryProject } from './types'

export type StoryMusicTabProps = {
  project: StoryProject
  patch: (value: Partial<StoryProject>) => void
  instruction: string
  setInstruction: (value: string) => void
  busy: StoryGenerationScope | null
  productionBusy: 'film' | 'music' | 'trailer' | null
  musicQueue: StoryMusicQueue | null
  musicCueBusy: string
  newSongAction: 'prompts' | 'audio' | null
  musicWritingReady: boolean
  minimaxConfigured: boolean
  storyVideoConfigurationReady: boolean
  workspace: string
  musicVersionStyle: Record<string, string>
  setMusicVersionStyle: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  musicVersionLanguage: Record<string, string>
  setMusicVersionLanguage: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  lyricsTranslationLanguage: Record<string, string>
  setLyricsTranslationLanguage: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  generate: (scope: StoryGenerationScope) => void
  generateAllMusicCues: () => void
  cancelMusicQueue: () => void
  createNewMusicVideoSong: (withAudio: boolean) => void
  createAllMusicCueVersions: () => void
  patchMusicCue: (cueId: string, changes: Partial<StoryMusicCue>) => void
  adaptMusicCueWithLlm: (cueId: string, includeLyria?: boolean) => void
  createMusicCueVersion: (cueId: string) => void
  translateMusicCueLyrics: (cueId: string) => void
  generateMusicCueAudio: (cueId: string) => void
  openMusicalTrailer: (candidateId?: string) => void
  onImportCustomMp3: (cueId: string) => void
  onImportLyria: (cueId: string) => void
  onCopied: (text: string) => void
  musicCoverRef: RefObject<HTMLInputElement | null>
  uploadCoverReference: (file?: File) => void
  writeStorySong: () => void
  adaptStoryLyrics: () => void
  translateManualSongLyrics: () => void
  createManualSongVersion: () => void
  generateMinimaxSongs: () => void
}

export function StoryMusicTab(props: StoryMusicTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, instruction, setInstruction, busy, musicQueue, musicCueBusy, newSongAction,
    musicWritingReady, minimaxConfigured, generate, generateAllMusicCues, cancelMusicQueue,
    createNewMusicVideoSong, createAllMusicCueVersions, musicVersionStyle, setMusicVersionStyle, musicVersionLanguage,
    setMusicVersionLanguage, onImportCustomMp3,
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
              disabled={musicBusy || !musicWritingReady || !minimaxConfigured}
              onClick={() => void createNewMusicVideoSong(true)}
              title={minimaxConfigured ? t('music.newSongAudioTitle') : t('music.minimaxKeyTitle')}>
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
                disabled={Boolean(busy || musicCueBusy) || !project.music.cues.length || !minimaxConfigured}
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

      <div className={`${panel} mb-4 grid md:grid-cols-[1fr_1fr_2fr] gap-3 items-end`}>
        <label className="block text-[10px] text-text-muted">{t('music.songModel')}
          <select className={`${input} mt-1`} value={project.music.model}
            onChange={event => patch({ music: { ...project.music, model: normalizeStoryMusicModel(event.target.value) } })}>
            <option value={ACE_STEP_MUSIC_MODEL}>{t('music.aceStepDefault')}</option>
            <option value="music-3.0">{t('music.music30Unavailable')}</option>
            <option value="music-2.6">{t('music.music26')}</option>
          </select>
        </label>
        <div className="text-[10px] text-text-muted">{t('music.oneResultHint')}</div>
        <div className={`rounded-md border px-3 py-2 text-[10px] ${minimaxConfigured ? 'border-emerald-500/30 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
          {minimaxConfigured ? t('music.minimaxReady') : t('music.minimaxMissing')}
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

      {(['world', 'character', 'story'] as const).map(kind => {
        const cues = project.music.cues.filter(cue => cue.kind === kind)
        if (!cues.length) return null
        const heading = kind === 'world' ? t('music.worldAmbience')
          : kind === 'character' ? t('music.characterThemes') : t('music.storySongs')
        return (
          <section key={kind} className="mb-5">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">{heading}</h3>
            <div className="space-y-3">
              {cues.map(cue => <MusicCueCard key={cue.id} cue={cue} kind={kind} {...props} />)}
            </div>
          </section>
        )
      })}

      {!project.music.cues.length && (
        <div className={`${panel} mb-5 py-12 text-center`}>
          <Music size={30} className="mx-auto mb-3 text-pink-400" />
          <p className="text-sm text-text-primary">{t('music.emptyTitle')}</p>
          <p className="mt-1 text-xs text-text-muted">{t('music.emptyHint')}</p>
        </div>
      )}

      <ManualSongPanel {...props} />
    </>
  )
}

function MusicCueCard({
  cue, kind, project, patchMusicCue, musicQueue, musicCueBusy, musicWritingReady, minimaxConfigured,
  storyVideoConfigurationReady, workspace, musicVersionStyle, setMusicVersionStyle, musicVersionLanguage,
  setMusicVersionLanguage, lyricsTranslationLanguage, setLyricsTranslationLanguage, adaptMusicCueWithLlm,
  createMusicCueVersion, translateMusicCueLyrics, generateMusicCueAudio, openMusicalTrailer, onImportCustomMp3,
  onImportLyria, onCopied,
}: StoryMusicTabProps & { cue: StoryMusicCue; kind: StoryMusicCue['kind'] }) {
  const { t } = useUiTranslation('storyLab')
  const targetName = cue.kind === 'character'
    ? project.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
    : cue.kind === 'world' ? (project.title || t('music.storyWorldFallback')) : cue.targetId
  const generatingAudio = musicCueBusy === `audio:${cue.id}`
  const adapting = musicCueBusy === `llm:${cue.id}`
  const translating = musicCueBusy === `translate:${cue.id}`
  const versioning = musicCueBusy === `version:${cue.id}`
  const queued = musicQueue?.ids.includes(cue.id)
  const cueBusy = Boolean(musicCueBusy || musicQueue)
  return (
    <article className={`${panel} space-y-3 ${generatingAudio ? 'border-pink-500/60' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="text-[9px] uppercase tracking-wide text-pink-300">{kind} · {targetName}</span>
          <input className={`${input} mt-1 font-medium`} value={cue.title}
            onChange={event => patchMusicCue(cue.id, { title: event.target.value })}
            aria-label={t('music.titleAria', { name: targetName })} />
        </div>
        {queued && <span className="rounded bg-pink-500/10 px-2 py-1 text-[9px] text-pink-300">{t('music.queued')}</span>}
      </div>
      <div className="grid xl:grid-cols-[minmax(0,0.85fr)_minmax(360px,1.15fr)] gap-3">
        <div className="space-y-2.5">
          <Field label={t('music.purpose')} value={cue.purpose}
            onChange={purpose => patchMusicCue(cue.id, { purpose })} rows={2} />
          <Field label={t('music.exampleSong')} value={cue.referenceSong}
            onChange={referenceSong => patchMusicCue(cue.id, { referenceSong })} rows={2}
            placeholder={t('music.exampleSongPlaceholder')} />
          <p className="text-[9px] text-text-muted">{t('music.exampleSongHint')}</p>
          <Field label={t('music.desiredStyle')} value={cue.brief}
            onChange={brief => patchMusicCue(cue.id, { brief })} rows={3} />
          <div className="grid grid-cols-2 gap-2">
            <label className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-[10px] text-text-secondary">
              <input type="checkbox" checked={cue.instrumental}
                onChange={event => patchMusicCue(cue.id, { instrumental: event.target.checked })} />
              {t('music.instrumental')}
            </label>
            <label className="block text-[10px] text-text-muted">{t('music.targetDuration')}
              <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                value={cue.durationSeconds}
                onChange={event => patchMusicCue(cue.id, { durationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) })} />
            </label>
          </div>
          <p className="text-[9px] text-text-muted">{t('music.durationHint')}</p>
          <button className={`${button} w-full`} disabled={cueBusy || !cue.referenceSong.trim()}
            onClick={() => void adaptMusicCueWithLlm(cue.id)}>
            {adapting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {cue.instrumental ? t('music.adaptPrompt') : t('music.adaptPromptLyrics')}
          </button>
          <div className="space-y-2 rounded-lg border border-purple-500/30 bg-purple-500/5 p-2.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-200"><Palette size={12} /> {t('music.newVersionTitle')}</div>
            <input className={input} value={musicVersionStyle[cue.id] || ''}
              onChange={event => setMusicVersionStyle(current => ({ ...current, [cue.id]: event.target.value }))}
              placeholder={t('music.newStyleExample')} />
            <input className={input} value={musicVersionLanguage[cue.id] || ''}
              onChange={event => setMusicVersionLanguage(current => ({ ...current, [cue.id]: event.target.value }))}
              placeholder={t('music.newLanguageCurrent', { language: cue.lyricsLanguage || project.language })} />
            <button className={`${button} w-full border-purple-500/60 text-purple-200`}
              disabled={cueBusy || !musicWritingReady}
              onClick={() => void createMusicCueVersion(cue.id)}>
              {versioning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />} {cue.instrumental ? t('music.rewriteStyle') : t('music.rewriteStyleLyrics')}
            </button>
            <p className="text-[9px] text-text-muted">{t('music.leaveEmptyHint')}</p>
          </div>
        </div>
        <div className="space-y-3">
          <div className="space-y-2.5 rounded-lg border border-pink-500/30 bg-pink-500/5 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h4 className="text-xs font-semibold text-pink-200">{t('music.minimaxRequest')}</h4>
                <p className="mt-0.5 text-[9px] text-text-muted">{t('music.minimaxRequestHint')}</p>
              </div>
              <span className="shrink-0 rounded border border-pink-500/30 px-2 py-1 text-[9px] text-pink-200">{project.music.model}</span>
            </div>
            <Field required label={t('music.promptChars', { count: cue.style.trim().length })} value={cue.style}
              onChange={style => patchMusicCue(cue.id, { style })} rows={3} />
            <p className="text-[9px] text-text-muted">{t('music.promptHint')}</p>
            {!cue.instrumental && <Field required label={t('music.lyricsStructured')} value={cue.lyrics}
              onChange={lyrics => patchMusicCue(cue.id, { lyrics })} rows={10} />}
            {!cue.instrumental && (
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                <label className="block text-[10px] text-text-muted">{t('music.translateTo')}
                  <input className={`${input} mt-1`} value={lyricsTranslationLanguage[cue.id] || ''}
                    onChange={event => setLyricsTranslationLanguage(current => ({ ...current, [cue.id]: event.target.value }))}
                    placeholder={t('music.translatePlaceholder')} />
                </label>
                <button className={`${button} self-end`} disabled={cueBusy || !musicWritingReady || !cue.lyrics.trim()}
                  onClick={() => void translateMusicCueLyrics(cue.id)}>
                  {translating ? <Loader2 size={13} className="animate-spin" /> : <Languages size={13} />} {t('music.translate')}
                </button>
              </div>
            )}
            {!cue.instrumental && <p className="text-[9px] text-text-muted">{t('music.translateHint')}</p>}
            {!cue.instrumental && cue.lyrics.trim() && !MINIMAX_LYRIC_SECTION.test(cue.lyrics) && (
              <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[9px] text-amber-200">
                {t('music.missingTags')}
              </p>
            )}
            <details className="rounded border border-border bg-bg-tertiary/70 p-2">
              <summary className="cursor-pointer text-[9px] text-text-secondary">{t('music.inspectPayload')}</summary>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[9px] text-text-muted">{miniMaxCuePayload(cue, project.music.model)}</pre>
            </details>
            <div className="grid sm:grid-cols-3 gap-2">
              <button className={button} onClick={() => {
                void navigator.clipboard.writeText(miniMaxCuePayload(cue, project.music.model))
                onCopied(t('music.payloadCopied', { title: cue.title }))
              }}><Copy size={12} /> {t('music.copyPayload')}</button>
              <button className={`${button} ${completeGenerationButton}`}
                disabled={cueBusy || !minimaxConfigured || !cue.style.trim() || (!cue.instrumental && (!cue.lyrics.trim() || !MINIMAX_LYRIC_SECTION.test(cue.lyrics)))}
                onClick={() => void generateMusicCueAudio(cue.id)}>
                {generatingAudio ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />} {t('music.generateTrack')}
              </button>
              <button className={button} disabled={cueBusy} onClick={() => onImportCustomMp3(cue.id)}>
                <Upload size={12} /> {t('music.importCustomMp3')}
              </button>
            </div>
          </div>
          <div className="space-y-2.5 rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h4 className="text-xs font-semibold text-blue-200">{t('music.lyriaTitle')}</h4>
                <p className="mt-0.5 text-[9px] text-text-muted">{t('music.lyriaHint')}</p>
              </div>
              <span className="shrink-0 rounded border border-blue-500/30 px-2 py-1 text-[9px] text-blue-200">lyria-3-pro-preview</span>
            </div>
            <Field label={t('music.lyriaPrompt')} value={cue.lyriaPrompt}
              onChange={lyriaPrompt => patchMusicCue(cue.id, { lyriaPrompt })} rows={14}
              placeholder={t('music.lyriaPlaceholder')} />
            <p className="text-[9px] text-text-muted">{t('music.lyriaDurationHint')}</p>
            <div className="grid sm:grid-cols-2 gap-2">
              <button className={button} disabled={cueBusy || !musicWritingReady}
                onClick={() => void adaptMusicCueWithLlm(cue.id, true)}>
                {adapting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('music.lyriaRefresh')}
              </button>
              <button className={button} disabled={!cue.lyriaPrompt.trim()} onClick={() => {
                void navigator.clipboard.writeText(cue.lyriaPrompt)
                onCopied(t('music.lyriaCopied', { title: cue.title }))
              }}><Copy size={12} /> {t('music.copyLyria')}</button>
              <a className={button} href="https://aistudio.google.com/u/1/new_music?model=lyria-3-pro-preview"
                target="_blank" rel="noreferrer">
                <ExternalLink size={12} /> {t('music.openLyria')}
              </a>
              <button className={button} disabled={cueBusy} onClick={() => onImportLyria(cue.id)}>
                <Upload size={12} /> {t('music.importGenerated')}
              </button>
            </div>
          </div>
        </div>
      </div>
      {cue.candidates.length > 0 && (
        <div className="space-y-2 border-t border-border pt-2">
          {cue.candidates.map(candidate => {
            const selected = cue.selectedCandidateId === candidate.id
            const label = musicCandidateDisplayName(candidate, cue.title, cue.lyricsLanguage || project.language, cue.candidates.indexOf(candidate) + 1)
            return (
              <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                <button type="button" className="w-full flex items-center justify-between gap-2 text-left text-[10px]"
                  onClick={() => patchMusicCue(cue.id, { selectedCandidateId: candidate.id })}>
                  <span className="text-text-primary">{label} · {candidate.model}</span>
                  <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : t('music.durationOnPlayback')}</span>
                </button>
                <audio src={api.getPlayableFileUrl(candidate.source, candidate.name, workspace)} controls preload="metadata" className="w-full h-8" />
                <button className={`${button} w-full`} disabled={cueBusy || !storyVideoConfigurationReady}
                  onClick={() => void openMusicalTrailer(candidate.id)}>
                  <Film size={12} /> {t('music.useInTrailer')}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </article>
  )
}

function ManualSongPanel({
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
            disabled={productionBusy === 'music' || !minimaxConfigured}
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
