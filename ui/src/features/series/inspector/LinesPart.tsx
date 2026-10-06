import { Loader2, MessageSquareText, Mic, RotateCcw } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { SeriesLineVoice, SeriesLineVoiceJob, SeriesScriptLine } from '../../../api/seriesShotInspector'
import { secondaryButton } from '../styles'
import { characterName, sectionId, type PartContext } from './context'
import { ListEditor, NumberInput, SelectInput, TextInput } from './fields'
import { InspectorSection } from './InspectorSection'
import { grid, languageName, lineLanguages, lineText, VOICE_ROOMS, voiceRoom, withField } from './model'
import { PlayButton } from './PlayButton'


export interface LineVoices {
  voices: SeriesLineVoice[]
  jobs: Record<string, SeriesLineVoiceJob>
  error: string
  record: (beatId: string, retake: boolean) => Promise<void>
}

/** Record the line (none yet) or take it again, or say it is recording now. */
function RecordButton({ line, job, onRecord }: { line: SeriesLineVoice; job?: SeriesLineVoiceJob; onRecord: (retake: boolean) => void }) {
  const { t } = useUiTranslation('seriesLab')
  if (job && (job.status === 'queued' || job.status === 'running')) return <span role="status" className="inline-flex items-center gap-1 text-[10px] text-violet-200">
    <Loader2 size={12} className="animate-spin" />{t(job.retake ? 'inspector.lines.retaking' : 'inspector.lines.recording')}</span>
  return <>
    <button type="button" className={`${secondaryButton} min-h-10 px-2 sm:min-h-0 sm:py-1`} onClick={() => onRecord(line.recorded)}>
      {line.recorded ? <RotateCcw size={13} /> : <Mic size={13} />}{t(line.recorded ? 'inspector.lines.retake' : 'inspector.lines.record')}</button>
    {!line.recorded && <span className="text-[10px] text-text-muted">{t('inspector.lines.notRecorded')}</span>}
  </>
}

function VoiceControls({ line, job, onRecord }: { line?: SeriesLineVoice; job?: SeriesLineVoiceJob; onRecord: (retake: boolean) => void }) {
  const { t } = useUiTranslation('seriesLab')
  if (!line) return null
  if (line.voice === false) return <p className="text-[10px] text-amber-300">{line.problem}</p>
  const room = t(`inspector.rooms.${voiceRoom(line.room)}`)
  return <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
    {line.recorded && <PlayButton url={line.url} label={t('inspector.lines.play', { number: line.number })} text={t('inspector.lines.voice')} />}
    {line.roomUrl && <PlayButton url={line.roomUrl} label={t('inspector.lines.playRoom', { room })} text={room} />}
    <RecordButton line={line} job={job} onRecord={onRecord} />
    {line.newerThanTake && <span className="rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] text-amber-200">{t('inspector.lines.newer')}</span>}
    {job?.status === 'failed' && <span role="alert" className="text-[10px] text-red-300">{job.error}</span>}
  </div>
}

function LineEditor({ context, line, change, languages }: {
  context: PartContext; line: SeriesScriptLine; change: (line: SeriesScriptLine) => void; languages: string[]
}) {
  const { t, i18n } = useUiTranslation('seriesLab')
  return <div className="space-y-2">
    <div className={grid}>
      <SelectInput title={t('inspector.lines.speaker')} value={line.who} onChange={value => change({ ...line, who: value })}
        options={context.series.characters.map(item => ({ value: item.id, label: item.name }))} />
      <TextInput title={t('inspector.lines.emotion')} value={line.emotion} onChange={value => change(withField(line, 'emotion', value))} />
      <TextInput title={t('inspector.lines.delivery')} value={line.delivery} onChange={value => change(withField(line, 'delivery', value))} />
      <NumberInput title={t('inspector.lines.pause')} value={line.pauseBefore} min={0} max={6} step={0.05}
        onChange={value => change(withField(line, 'pauseBefore', value))} />
      <SelectInput title={t('inspector.lines.room')} value={line.voiceRoom} empty={t('inspector.lines.roomInherit')}
        onChange={value => change(withField(line, 'voiceRoom', value))} options={VOICE_ROOMS.map(value => ({ value, label: t(`inspector.rooms.${value}`) }))} />
    </div>
    <TextInput multiline title={t('inspector.lines.text', { language: languageName(context.language, i18n.language) })} value={lineText(line, context.language)}
      onChange={value => change({ ...line, [context.language]: value })} />
    {languages.filter(language => language !== context.language).map(language => <TextInput key={language} multiline
      title={t('inspector.lines.text', { language: languageName(language, i18n.language) })} value={lineText(line, language)} onChange={value => change(withField(line, language, value))} />)}
  </div>
}

/** Dialogue: who says what, how, after which pause and in which room; each line's voice can be heard and recorded again. */
export function LinesPart({ context, voices }: { context: PartContext; voices: LineVoices }) {
  const { t } = useUiTranslation('seriesLab')
  const lines = (context.script?.lines || []) as SeriesScriptLine[]
  const languages = [...new Set(lines.flatMap(line => lineLanguages(line)))]
  const meta = (line: SeriesScriptLine) => [line.emotion, line.delivery,
    typeof line.pauseBefore === 'number' ? t('inspector.lines.pauseShort', { seconds: line.pauseBefore }) : '',
    line.voiceRoom ? t(`inspector.rooms.${voiceRoom(line.voiceRoom)}`) : ''].filter(Boolean).join(' · ')
  return <InspectorSection id={sectionId(context.shot.id, 'lines')} inspector={context.inspector} shotId={context.shot.id} section="lines"
    script={context.script} draft={context.drafts.lines} save={context.save} icon={<MessageSquareText size={14} />} title={t('inspector.lines.title')}
    summary={lines.length ? null : t('inspector.lines.empty')}
    view={lines.length > 0 && <>
      <ol className="mt-2 space-y-2">{lines.map((line, index) => {
        const voice = voices.voices[index]
        return <li key={index} className="rounded-lg border border-border bg-bg-primary p-2">
          <p className="text-[10px] text-text-muted"><span className="font-semibold text-text-primary">#{index + 1} {characterName(context.series, line.who)}</span>
            {meta(line) && ` · ${meta(line)}`}</p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-text-primary sm:text-xs">{lineText(line, context.language)}</p>
          <VoiceControls line={voice} job={voice ? voices.jobs[voice.beatId] : undefined} onRecord={retake => voice && void voices.record(voice.beatId, retake)} />
        </li>
      })}</ol>
      {voices.error && <p role="alert" className="mt-2 text-[11px] text-red-300">{voices.error}</p>}
      <p className="mt-2 text-[10px] text-text-muted">{t('inspector.lines.hint')}</p>
    </>}
    editor={({ draft, change }) => <ListEditor items={(draft.lines || []) as SeriesScriptLine[]} max={12} addLabel={t('inspector.lines.add')}
      itemLabel={index => t('inspector.lines.item', { number: index + 1 })}
      create={() => ({ who: context.series.characters[0]?.id || '', [context.language]: '' })}
      onChange={items => change({ ...draft, lines: items })}
      render={(line, update) => <LineEditor context={context} line={line} change={update} languages={languages} />} />} />
}
