import { Copy, ExternalLink, Film, Languages, Loader2, Music, Palette, RefreshCcw, Sparkles, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel, Field } from './storyLabChrome'
import { MINIMAX_LYRIC_SECTION, miniMaxCuePayload, musicCandidateDisplayName } from './storyLabMusic'
import type { StoryMusicCue } from './types'
import type { StoryMusicTabProps } from './StoryMusicTab'

export function MusicCueCard({
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
