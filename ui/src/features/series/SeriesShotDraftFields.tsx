import { SeriesField } from './components'
import { SeriesShotDurationControl } from './SeriesShotDurationControl'
import { inputClass, textareaClass } from './styles'
import type { SeriesProject, SeriesShot } from './types'
import { useUiTranslation } from '../../i18n'

export function SeriesShotDraftFields({
  shot, series, workspace, onChange,
}: {
  shot: SeriesShot
  series: SeriesProject
  workspace: string
  onChange: (shot: SeriesShot) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return (
    <>
      <div className="grid gap-2 sm:grid-cols-3">
        <SeriesShotDurationControl workspace={workspace} series={series} shot={shot} onChange={planned => onChange(planned)} />
        <SeriesField label={t('proposal.framing')}>
          <input aria-label={t('proposal.framing')} className={inputClass} value={shot.framing} onChange={event => onChange({ ...shot, framing: event.target.value })} />
        </SeriesField>
      </div>
      <div className="mt-2 grid gap-2 lg:grid-cols-2">
        <SeriesField label={t('proposal.camera')}>
          <textarea aria-label={t('proposal.camera')} className={textareaClass} value={shot.camera} onChange={event => onChange({ ...shot, camera: event.target.value })} />
        </SeriesField>
        <SeriesField label={t('proposal.action')}>
          <textarea aria-label={t('proposal.action')} className={textareaClass} value={shot.action} onChange={event => onChange({ ...shot, action: event.target.value })} />
        </SeriesField>
        <SeriesField label={t('proposal.prompt')}>
          <textarea aria-label={t('proposal.prompt')} className={textareaClass} value={shot.prompt} onChange={event => onChange({ ...shot, prompt: event.target.value })} />
        </SeriesField>
        <SeriesField label={t('proposal.negative')}>
          <textarea aria-label={t('proposal.negative')} className={textareaClass} value={shot.negativePrompt} onChange={event => onChange({ ...shot, negativePrompt: event.target.value })} />
        </SeriesField>
        <SeriesField label={t('proposal.audio')}>
          <textarea aria-label={t('proposal.audio')} className={textareaClass} value={shot.audioDirection || ''} onChange={event => onChange({ ...shot, audioDirection: event.target.value })} />
        </SeriesField>
      </div>
      {shot.dialogueBeats.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{t('proposal.dialogueInShot')}</p>
          {shot.dialogueBeats.map((line, lineIndex) => (
            <div key={line.id} className="grid gap-2 rounded-lg border border-border bg-bg-secondary p-2 md:grid-cols-[150px_1fr_120px]">
              <select aria-label={t('canon.character')} className={inputClass} value={line.characterId} onChange={event => onChange({
                ...shot,
                dialogueBeats: shot.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, characterId: event.target.value } : entry),
                visibleCharacterIds: shot.visibleCharacterIds.includes(event.target.value)
                  ? shot.visibleCharacterIds
                  : [...shot.visibleCharacterIds, event.target.value],
              })}>
                {series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
              <textarea aria-label={t('proposal.dialogue')} className={`${textareaClass} min-h-10`} value={line.text} onChange={event => onChange({
                ...shot,
                dialogueBeats: shot.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, text: event.target.value } : entry),
              })} />
              <SeriesField label={t('proposal.emotion')}>
                <input aria-label={t('proposal.emotion')} className={inputClass} value={line.emotion} onChange={event => onChange({
                  ...shot,
                  dialogueBeats: shot.dialogueBeats.map((entry, index) => index === lineIndex ? { ...entry, emotion: event.target.value } : entry),
                })} />
              </SeriesField>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
