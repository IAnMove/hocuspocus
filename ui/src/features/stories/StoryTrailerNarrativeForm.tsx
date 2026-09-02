import { useUiTranslation } from '../../i18n'
import { button, input, panel } from './storyLabChrome'
import type { StoryTrailerFormat, StoryTrailerIntensity, StoryTrailerNarration, StoryTrailerSpoiler } from './types'
import type { StoryTrailerTabProps } from './StoryTrailerTab'

export function StoryTrailerNarrativeForm(props: StoryTrailerTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, trailerDuration, setTrailerDuration, trailerDirection, setTrailerDirection, trailerTagline,
    setTrailerTagline, trailerFormat, setTrailerFormat, trailerNarration, setTrailerNarration, trailerSpoiler,
    setTrailerSpoiler, trailerIntensity, setTrailerIntensity, trailerTitleCards, setTrailerTitleCards, markTrailerTouched,
  } = props
  return (
    <div className={`${panel} space-y-4`}>
      <div><h3 className="text-sm font-semibold text-text-primary">{t('trailer.narrativeDirection')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('trailer.narrativeHint')}</p></div>
      <label className="block text-[10px] text-text-muted">{t('trailer.promiseLabel')}
        <textarea className={`${input} mt-1`} rows={4} value={trailerDirection} onChange={event => { markTrailerTouched(); setTrailerDirection(event.target.value) }} aria-label={t('trailer.directionAria')} />
      </label>
      <label className="block text-[10px] text-text-muted">{t('trailer.optionalTagline')}
        <input className={`${input} mt-1`} value={trailerTagline} onChange={event => { markTrailerTouched(); setTrailerTagline(event.target.value) }} placeholder={project.logline || t('trailer.taglinePlaceholder')} />
      </label>
      <div>
        <p className="mb-1.5 text-[10px] text-text-muted">{t('trailer.duration')}</p>
        <div className="grid grid-cols-4 gap-1.5">
          {[30, 45, 60, 90].map(seconds => <button key={seconds} type="button" className={`${button} ${trailerDuration === seconds ? 'border-amber-400/70 bg-amber-500/10 text-amber-100' : ''}`} onClick={() => { markTrailerTouched(); setTrailerDuration(seconds) }}>{seconds}s</button>)}
        </div>
        <input className={`${input} mt-2`} type="number" min={15} max={180} step={5} value={trailerDuration} onChange={event => { markTrailerTouched(); setTrailerDuration(Math.max(15, Math.min(180, Number(event.target.value) || 60))) }} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block text-[10px] text-text-muted">{t('trailer.format')}
          <select className={`${input} mt-1`} value={trailerFormat} onChange={event => { markTrailerTouched(); setTrailerFormat(event.target.value as StoryTrailerFormat) }}>
            <option value="theatrical">{t('trailer.formatTheatrical')}</option>
            <option value="teaser">{t('trailer.formatTeaser')}</option>
            <option value="character">{t('trailer.formatCharacter')}</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">{t('trailer.voices')}
          <select className={`${input} mt-1`} value={trailerNarration} onChange={event => { markTrailerTouched(); setTrailerNarration(event.target.value as StoryTrailerNarration) }}>
            <option value="hybrid">{t('trailer.voicesHybrid')}</option>
            <option value="voice_over">{t('trailer.voicesVoiceOver')}</option>
            <option value="dialogue">{t('trailer.voicesDialogue')}</option>
            <option value="visual">{t('trailer.voicesVisual')}</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">{t('trailer.spoiler')}
          <select className={`${input} mt-1`} value={trailerSpoiler} onChange={event => { markTrailerTouched(); setTrailerSpoiler(event.target.value as StoryTrailerSpoiler) }}>
            <option value="mystery">{t('trailer.spoilerMystery')}</option>
            <option value="balanced">{t('trailer.spoilerBalanced')}</option>
            <option value="revealing">{t('trailer.spoilerRevealing')}</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">{t('trailer.intensity')}
          <select className={`${input} mt-1`} value={trailerIntensity} onChange={event => { markTrailerTouched(); setTrailerIntensity(event.target.value as StoryTrailerIntensity) }}>
            <option value="rising">{t('trailer.intensityRising')}</option>
            <option value="relentless">{t('trailer.intensityRelentless')}</option>
            <option value="prestige">{t('trailer.intensityPrestige')}</option>
          </select>
        </label>
      </div>
      <label className={`flex items-start gap-2 rounded-md border p-2 ${trailerTitleCards && !project.allowClipText ? 'border-amber-400/50 bg-amber-500/10' : 'border-border bg-bg-primary/30'}`}>
        <input type="checkbox" checked={trailerTitleCards} onChange={event => { markTrailerTouched(); setTrailerTitleCards(event.target.checked) }} className="mt-0.5 accent-amber-400" />
        <span><span className="block text-[10px] font-medium text-text-primary">{t('trailer.titleCards')}</span><span className="block text-[9px] text-text-muted">{t('trailer.titleCardsHint')}</span></span>
      </label>
      {trailerTitleCards && !project.allowClipText && <button type="button" className={`${button} w-full border-amber-400/50 text-amber-200`} onClick={() => patch({ allowClipText: true })}>{t('trailer.allowClipText')}</button>}
    </div>
  )
}
