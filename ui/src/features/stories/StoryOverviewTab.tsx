import { Palette, RefreshCcw, Sparkles } from 'lucide-react'
import { EditableLanguageInput } from '../../components/common/EditableLanguageInput'
import { useUiTranslation } from '../../i18n'
import {
  button, input, panel, requiredInput, Field, SectionHeader, requiredPreparationButton,
  type StoryLabSectionTabProps,
} from './storyLabChrome'
import { storyRenderStyle } from './model'
import { StoryProviderPanel } from './StoryProviderPanel'
import type { StoryProject } from './types'

const GENRES = [
  'Adventure', 'Action', 'Comedy', 'Drama', 'Fantasy', 'Science fiction', 'Horror',
  'Mystery', 'Thriller', 'Romance', 'Historical', 'Crime', 'Slice of life',
  'Western', 'Cyberpunk', 'Noir', 'Satire',
]
const TONES = [
  'Cinematic', 'Epic', 'Lighthearted', 'Dark', 'Humorous', 'Dramatic',
  'Suspenseful', 'Emotional', 'Hopeful', 'Gritty', 'Whimsical', 'Mysterious',
  'Romantic', 'Melancholic', 'Satirical', 'Family-friendly',
]
const CHARACTER_STYLE_PRESETS = [
  ['presetPhotoreal', 'Photorealistic live-action people, natural skin texture, anatomically realistic proportions, authentic hair and fabric, cinematic photographic detail'],
  ['presetClay', 'Handmade claymation characters sculpted from plasticine, visible fingerprints and tool marks, tactile matte clay surfaces, stop-motion proportions'],
  ['presetAnime', '2D anime characters, clean expressive linework, consistent cel shading, stylized facial proportions, illustrated skin and hair, never photorealistic'],
] as const

function Choice({
  label, value, options, onChange, required = false,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
  required?: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const custom = !options.includes(value)
  return (
    <label className={`block text-[10px] ${required ? 'text-violet-200' : 'text-text-muted'}`}>
      {label}{required && <span className="ml-1 text-violet-300" title={t('chrome.required')}>●</span>}
      <select
        className={`${input} ${required ? requiredInput : ''} mt-1`}
        value={custom ? '__other__' : value}
        onChange={event => onChange(event.target.value === '__other__' ? '' : event.target.value)}
        required={required}
        aria-required={required}
      >
        {options.map(option => <option key={option}>{option}</option>)}
        <option value="__other__">{t('overview.other')}</option>
      </select>
      {custom && <input className={`${input} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={label} />}
    </label>
  )
}

export function StoryOverviewTab({
  project, patch, busy, instruction, setInstruction, generate, approve, isApproved,
  setTrailerDuration, protagonistReferenceReady, promptHealthWarnings, writeStyleIntoPrompts,
  regenerateStyledReferences, imageBusy, referenceBatchBusy, styledReferenceTargetCount, onProfileModeChange,
}: StoryLabSectionTabProps & {
  patch: (value: Partial<StoryProject>) => void
  setTrailerDuration: (value: number) => void
  protagonistReferenceReady: boolean
  promptHealthWarnings: string[]
  writeStyleIntoPrompts: () => void
  regenerateStyledReferences: () => void
  imageBusy: string
  referenceBatchBusy: boolean
  styledReferenceTargetCount: number
  onProfileModeChange: (useGlobalProfile: boolean) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const title = project.projectType === 'music_video' ? t('overview.titleMusic')
    : project.projectType === 'trailer' ? t('overview.titleTrailer')
      : project.projectType === 'quick_video' ? t('overview.titleQuick') : t('overview.titleStory')
  const description = project.projectType === 'music_video' ? t('overview.descriptionMusic')
    : project.projectType === 'trailer' ? t('overview.descriptionTrailer')
      : project.projectType === 'quick_video' ? t('overview.descriptionQuick') : t('overview.descriptionStory')
  return (
    <>
      <div id="story-review-overview" className="scroll-mt-4">
        <SectionHeader
          title={title}
          description={description}
          scope="overview" busy={busy} approved={isApproved('overview')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('overview')}
        />
      </div>
      <div className={`${panel} mb-4 border-accent-blue/30 bg-accent-blue/5`}>
        <Field
          required
          label={t('overview.generalIdea')}
          value={project.creativeBrief.generalIdea}
          onChange={generalIdea => patch({ creativeBrief: { ...project.creativeBrief, generalIdea } })}
          rows={9}
          placeholder={t('overview.generalIdeaPlaceholder')}
        />
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-[10px] text-text-muted">{t('overview.generalIdeaHint')}</p>
          <button type="button" className={`${button} ${requiredPreparationButton}`} disabled={Boolean(busy)} onClick={() => generate('all')}>
            <Sparkles size={13} /> {t('overview.interpretAll')}
          </button>
        </div>
      </div>
      {project.projectType === 'music_video' && (
        <div className={`${panel} mb-4 grid md:grid-cols-2 gap-3 border-pink-500/20`}>
          <div className="md:col-span-2"><Field required label={t('overview.musicContext')} value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={4} placeholder={t('overview.musicContextPlaceholder')} /></div>
          <Field required label={t('overview.performer')} value={project.creativeBrief.performer} onChange={performer => patch({ creativeBrief: { ...project.creativeBrief, performer } })} rows={3} placeholder={t('overview.performerPlaceholder')} />
          <Field required label={t('overview.musicStyle')} value={project.creativeBrief.musicStyle} onChange={musicStyle => patch({ creativeBrief: { ...project.creativeBrief, musicStyle }, music: { ...project.music, style: musicStyle } })} rows={3} placeholder={t('overview.musicStylePlaceholder')} />
          <div className="md:col-span-2"><Field required label={t('overview.songStory')} value={project.creativeBrief.songStory} onChange={songStory => patch({ creativeBrief: { ...project.creativeBrief, songStory }, music: { ...project.music, brief: songStory } })} rows={5} placeholder={t('overview.songStoryPlaceholder')} /></div>
          <label className="block text-[10px] text-text-muted">
            {t('overview.targetDuration', { seconds: project.creativeBrief.durationSeconds })}
            <input type="range" min={30} max={360} step={5} className="mt-2 w-full accent-accent-blue" value={project.creativeBrief.durationSeconds}
              onChange={event => {
                const durationSeconds = Number(event.target.value)
                patch({ creativeBrief: { ...project.creativeBrief, durationSeconds }, music: { ...project.music, targetDurationSeconds: durationSeconds } })
              }} />
          </label>
          <p className="self-end text-[10px] text-text-muted">{t('overview.musicPlanHint')}</p>
        </div>
      )}
      {project.projectType === 'trailer' && (
        <div className={`${panel} mb-4 grid gap-3 border-amber-500/20 md:grid-cols-2`}>
          <div className="md:col-span-2"><Field required label={t('overview.trailerContext')} value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={4} placeholder={t('overview.trailerContextPlaceholder')} /></div>
          <Field required label={t('overview.trailerSubjects')} value={project.creativeBrief.subjects} onChange={subjects => patch({ creativeBrief: { ...project.creativeBrief, subjects } })} rows={4} placeholder={t('overview.trailerSubjectsPlaceholder')} />
          <Field required label={t('overview.trailerSetting')} value={project.creativeBrief.setting} onChange={setting => patch({ creativeBrief: { ...project.creativeBrief, setting } })} rows={4} placeholder={t('overview.trailerSettingPlaceholder')} />
          <div className="md:col-span-2"><Field required label={t('overview.trailerAction')} value={project.creativeBrief.action} onChange={action => patch({ creativeBrief: { ...project.creativeBrief, action } })} rows={5} placeholder={t('overview.trailerActionPlaceholder')} /></div>
          <label className="block text-[10px] text-text-muted">
            {t('overview.targetDuration', { seconds: project.creativeBrief.durationSeconds })}
            <input type="range" min={15} max={180} step={5} className="mt-2 w-full accent-amber-400" value={project.creativeBrief.durationSeconds}
              onChange={event => {
                const durationSeconds = Number(event.target.value)
                setTrailerDuration(durationSeconds)
                patch({ creativeBrief: { ...project.creativeBrief, durationSeconds } })
              }} />
          </label>
          <p className="self-end text-[10px] text-text-muted">{t('overview.trailerPlanHint')}</p>
        </div>
      )}
      {project.projectType === 'quick_video' && (
        <div className={`${panel} mb-4 grid md:grid-cols-2 gap-3 border-cyan-500/20`}>
          <div className="md:col-span-2"><Field required label={t('overview.quickContext')} value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={3} placeholder={t('overview.quickContextPlaceholder')} /></div>
          <Field required label={t('overview.quickSubjects')} value={project.creativeBrief.subjects} onChange={subjects => patch({ creativeBrief: { ...project.creativeBrief, subjects } })} rows={3} placeholder={t('overview.quickSubjectsPlaceholder')} />
          <Field required label={t('overview.quickSetting')} value={project.creativeBrief.setting} onChange={setting => patch({ creativeBrief: { ...project.creativeBrief, setting } })} rows={3} placeholder={t('overview.quickSettingPlaceholder')} />
          <div className="md:col-span-2"><Field required label={t('overview.quickAction')} value={project.creativeBrief.action} onChange={action => patch({ creativeBrief: { ...project.creativeBrief, action } })} rows={5} placeholder={t('overview.quickActionPlaceholder')} /></div>
          <label className="block text-[10px] text-text-muted">{t('overview.quickFormat')}
            <select className={`${input} mt-1`} value={project.creativeBrief.quickFormat}
              onChange={event => patch({ creativeBrief: { ...project.creativeBrief, quickFormat: event.target.value as StoryProject['creativeBrief']['quickFormat'] } })}>
              <option value="dialogue">{t('overview.formatDialogue')}</option><option value="meme">{t('overview.formatMeme')}</option><option value="parody">{t('overview.formatParody')}</option>
              <option value="sketch">{t('overview.formatSketch')}</option><option value="viral">{t('overview.formatViral')}</option><option value="announcement">{t('overview.formatAnnouncement')}</option>
            </select>
          </label>
          <label className="block text-[10px] text-text-muted">
            {t('overview.targetDuration', { seconds: project.creativeBrief.durationSeconds })}
            <input type="range" min={5} max={120} step={5} className="mt-2 w-full accent-accent-blue" value={project.creativeBrief.durationSeconds}
              onChange={event => patch({ creativeBrief: { ...project.creativeBrief, durationSeconds: Number(event.target.value) } })} />
          </label>
        </div>
      )}
      <div className="grid xl:grid-cols-[1fr_360px] gap-4">
        <div className={`${panel} grid md:grid-cols-2 gap-3`}>
          <Field required label={t('overview.title')} value={project.title} onChange={titleValue => patch({ title: titleValue })} />
          <label className="block text-[10px] text-violet-200">
            {t('overview.language')}<span className="ml-1 text-violet-300" title={t('chrome.required')}>●</span>
            <EditableLanguageInput
              className={`${input} ${requiredInput} mt-1`}
              value={project.language}
              onChange={language => patch({ language })}
              required
            />
          </label>
          <label className="block text-[10px] text-violet-200">
            {t('overview.spokenLanguage')}
            <select className={`${input} mt-1`} value={project.spokenLanguage} onChange={event => patch({ spokenLanguage: event.target.value })}>
              <option value="">{t('overview.spokenAuto')}</option>
              <option value="Español de España">Español de España</option>
              <option value="Español latinoamericano">Español latinoamericano</option>
              <option value="English">English</option>
              <option value="French">Français</option>
              <option value="Italian">Italiano</option>
            </select>
            <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">{t('overview.spokenHint')}</span>
          </label>
          {project.projectType === 'music_video' && <label className="block text-[10px] text-violet-200">
            {t('overview.locationVariety')}
            <select className={`${input} mt-1`} value={project.locationVariety} onChange={event => patch({ locationVariety: event.target.value as StoryProject['locationVariety'] })}>
              <option value="balanced">{t('overview.locationBalanced')}</option>
              <option value="single_location">{t('overview.locationSingle')}</option>
            </select>
          </label>}
          <div className="md:col-span-2 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 space-y-2">
            <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
              <input type="checkbox" checked={project.protagonistConsistency} onChange={event => patch({ protagonistConsistency: event.target.checked, protagonistCharacterId: event.target.checked ? (project.protagonistCharacterId || project.characters[0]?.id || '') : project.protagonistCharacterId, ...(event.target.checked && project.musicVideoGenerationMode === 'direct_video' ? { musicVideoGenerationMode: 'image_guided' as const } : {}) })} className="mt-0.5 accent-violet-400" />
              <span><span className="block text-violet-200">{t('overview.fixProtagonist')}</span><span className="block text-[9px] text-text-muted">{t('overview.fixProtagonistHint')}</span></span>
            </label>
            {project.protagonistConsistency && <select className={input} value={project.protagonistCharacterId} onChange={event => patch({ protagonistCharacterId: event.target.value })}>
              <option value="">{t('overview.selectProtagonist')}</option>
              {project.characters.map(character => <option key={character.id} value={character.id}>{character.name || t('overview.unnamed')}</option>)}
            </select>}
            {project.protagonistConsistency && <p className={`text-[9px] ${protagonistReferenceReady ? 'text-emerald-200' : 'text-amber-300'}`}>{protagonistReferenceReady ? t('overview.protagonistReady') : t('overview.protagonistMissing')}</p>}
          </div>
          {promptHealthWarnings.length > 0 && <div className="md:col-span-2 rounded-lg border border-amber-500/35 bg-amber-500/5 p-3">
            <p className="text-[10px] font-medium text-amber-200">{t('overview.promptHealth')}</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-[9px] leading-relaxed text-amber-100">{promptHealthWarnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
          </div>}
          {project.projectType === 'full_story' && (
            <>
              <Choice required label={t('overview.genre')} value={project.genre} options={GENRES} onChange={genre => patch({ genre })} />
              <Choice required label={t('overview.tone')} value={project.tone} options={TONES} onChange={tone => patch({ tone })} />
              <Field label={t('overview.audience')} value={project.audience} onChange={audience => patch({ audience })} />
              <Field label={t('overview.theme')} value={project.theme} onChange={theme => patch({ theme })} />
              <Field required label={t('overview.premise')} value={project.premise} onChange={premise => patch({ premise })} rows={5} placeholder={t('overview.premisePlaceholder')} />
            </>
          )}
          <Field required label={t('overview.visualStyle')} value={project.visualStyle} onChange={visualStyle => patch({ visualStyle })} rows={5} placeholder={t('overview.visualStylePlaceholder')} />
          <div className="space-y-1.5">
            <Field
              required
              label={t('overview.characterVisualStyle')}
              value={project.characterVisualStyle}
              onChange={characterVisualStyle => patch({ characterVisualStyle })}
              rows={5}
              placeholder={t('overview.characterVisualStylePlaceholder')}
            />
            <div className="flex flex-wrap gap-1.5">
              {CHARACTER_STYLE_PRESETS.map(([labelKey, value]) => (
                <button
                  key={labelKey}
                  type="button"
                  className={`${button} px-2 py-1 text-[10px] ${project.characterVisualStyle === value ? 'border-accent-blue text-accent-blue' : ''}`}
                  onClick={() => patch({ characterVisualStyle: value, enforceVisualStyle: true })}
                >
                  {t(`overview.${labelKey}`)}
                </button>
              ))}
            </div>
          </div>
          <div className="md:col-span-2 rounded-lg border border-border bg-bg-tertiary/50 p-3 space-y-2">
            <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={project.enforceVisualStyle}
                onChange={event => patch({ enforceVisualStyle: event.target.checked })}
              />
              <span>
                <span className="font-medium text-text-primary">{t('overview.enforceStyles')}</span>
                <span className="block mt-0.5 text-[10px] text-text-muted">{t('overview.enforceStylesHint')}</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={project.allowClipText}
                onChange={event => patch({ allowClipText: event.target.checked })}
              />
              <span>
                <span className="font-medium text-text-primary">{t('overview.allowClipText')}</span>
                <span className="block mt-0.5 text-[10px] text-text-muted">{t('overview.allowClipTextHint')}</span>
              </span>
            </label>
            <div className="flex flex-wrap gap-2">
              <button className={button} disabled={!storyRenderStyle(project)} onClick={writeStyleIntoPrompts}>
                <Palette size={13} /> {t('overview.writeStyleLock')}
              </button>
              <button className={button} disabled={!storyRenderStyle(project) || !styledReferenceTargetCount || Boolean(imageBusy) || referenceBatchBusy} onClick={regenerateStyledReferences}>
                <RefreshCcw size={13} /> {t(styledReferenceTargetCount === 1 ? 'overview.prepareReferences' : 'overview.prepareReferences_plural', { count: styledReferenceTargetCount })}
              </button>
            </div>
            <p className="text-[9px] leading-relaxed text-text-muted">
              {t('overview.styleLockHint')}
            </p>
          </div>
          <div className="md:col-span-2 border-t border-border pt-3">
            <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-text-muted">
              {project.projectType === 'full_story' ? t('overview.treatmentStory') : t('overview.treatmentOther')}
            </p>
            <div className="space-y-3">
              <Field label={t('overview.logline')} value={project.logline} onChange={logline => patch({ logline })} rows={2} />
              <Field label={t('overview.synopsis')} value={project.synopsis} onChange={synopsis => patch({ synopsis })} rows={8} />
              <Field label={t('overview.ending')} value={project.ending} onChange={ending => patch({ ending })} rows={3} />
            </div>
          </div>
        </div>
        <StoryProviderPanel project={project} patch={patch} onProfileModeChange={onProfileModeChange} />
      </div>
    </>
  )
}
