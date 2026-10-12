import type { ReactNode } from 'react'
import { Music } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { sectionId, type PartContext } from './context'
import { FileInput, NumberInput, SelectInput, TextInput } from './fields'
import { InspectorSection, type DraftProps } from './InspectorSection'
import { grid, scoreCue, VOICE_ROOMS, voiceRoom, withField, workspaceFileUrl } from './model'
import { PlayButton } from './PlayButton'
import { useShotFiles } from './useInspectorData'

type Music = { file?: string; volume?: number; start?: number; [language: string]: unknown }
type Foley = { prompt?: string; volume?: number }

/** One sound the shot plays (or plays under), with its play button. */
function Heard({ url, label, children }: { url?: string; label: string; children: ReactNode }) {
  return <li className="flex flex-wrap items-center gap-2"><PlayButton url={url} label={label} /><span className="text-text-muted">{children}</span></li>
}

/** The shot's own music, or that it has none. */
function MusicRow({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const music = context.script?.music as Music | undefined
  if (!music?.file) return <li className="text-text-muted">{t('inspector.sound.noMusic')}</li>
  return <Heard url={workspaceFileUrl(context.workspace, music.file)} label={t('inspector.sound.playMusic')}>
    {t('inspector.sound.music', { file: music.file, volume: music.volume ?? 0.6 })}</Heard>
}

/** The episode's score cue this shot plays under (silenced by the shot's own music). */
function ScoreRow({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const score = scoreCue(context.episode, context.shot)
  if (!score) return null
  const own = Boolean((context.script?.music as Music | undefined)?.file)
  return <Heard url={workspaceFileUrl(context.workspace, score.file)} label={t('inspector.sound.playScore')}>
    {t(own ? 'inspector.sound.scoreSilenced' : 'inspector.sound.score', { file: score.file })}</Heard>
}

/** The location's ambience, mixed in the shot or laid across the cut. */
function AmbienceRow({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const design = context.series.soundDesign || {}
  const ambience = (design.ambienceByLocation || {})[context.shot.locationId || '']
  if (!ambience?.file) return null
  return <Heard url={workspaceFileUrl(context.workspace, ambience.file)} label={t('inspector.sound.playAmbience')}>
    {t(design.ambienceMode === 'episode' ? 'inspector.sound.ambienceEpisode' : 'inspector.sound.ambience', { file: ambience.file })}</Heard>
}

/** The room the voices are heard in (the shot's, else its location's) and the foley. */
function VoicesAndFoley({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const room = context.script?.voiceRoom
  const locationRoom = (context.series.soundDesign?.roomByLocation || {})[context.shot.locationId || '']
  const foley = context.script?.foley as Foley | undefined
  const inherited = !room && locationRoom ? ` · ${t('inspector.sound.roomFromLocation')}` : ''
  return <>
    <li>{t('inspector.sound.room', { room: t(`inspector.rooms.${voiceRoom(room || locationRoom)}`) })}{inherited}</li>
    {foley?.prompt ? <li>{t('inspector.sound.foley', { prompt: foley.prompt, volume: foley.volume ?? 0.5 })}</li>
      : <li className="text-text-muted">{t('inspector.sound.noFoley')}</li>}
  </>
}

function SoundSummary({ context }: { context: PartContext }) {
  return <ul className="space-y-1">
    <MusicRow context={context} /><ScoreRow context={context} /><AmbienceRow context={context} /><VoicesAndFoley context={context} />
  </ul>
}

function SoundEditor({ context, draft, change }: DraftProps & { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const files = useShotFiles(context.workspace, context.series.id, 'audio')
  const nextMusic = (draft.music || {}) as Music
  const nextFoley = (draft.foley || {}) as Foley
  // A block left empty is removed; a half-written one stays in the draft (the save says what it lacks).
  const setBlock = (key: 'music' | 'foley', block: Record<string, unknown>, field: string, value: unknown) => {
    const updated = withField(block, field, value)
    change(withField(draft, key, Object.keys(updated).length ? updated : undefined))
  }
  return <div className="space-y-3">
    <div className={grid}>
      <FileInput title={t('inspector.sound.musicFile')} value={nextMusic.file} files={files} onChange={value => setBlock('music', nextMusic, 'file', value)} />
      <NumberInput title={t('inspector.sound.volume')} value={nextMusic.volume} min={0} max={1} onChange={value => setBlock('music', nextMusic, 'volume', value)} />
      <NumberInput title={t('inspector.sound.musicStart')} value={nextMusic.start} min={0} max={600} onChange={value => setBlock('music', nextMusic, 'start', value)} />
      <SelectInput title={t('inspector.sound.voiceRoom')} value={draft.voiceRoom} empty={t('inspector.sound.roomLocation')}
        onChange={value => change(withField(draft, 'voiceRoom', value))} options={VOICE_ROOMS.map(value => ({ value, label: t(`inspector.rooms.${value}`) }))} />
    </div>
    <div className="grid gap-2 @md:grid-cols-[1fr_8rem]">
      <TextInput multiline title={t('inspector.sound.foleyPrompt')} value={nextFoley.prompt} placeholder={t('inspector.sound.foleyPlaceholder')}
        onChange={value => setBlock('foley', nextFoley, 'prompt', value)} />
      <NumberInput title={t('inspector.sound.foleyVolume')} value={nextFoley.volume} min={0.05} max={2} onChange={value => setBlock('foley', nextFoley, 'volume', value)} />
    </div>
    <p className="text-[10px] text-text-muted">{t('inspector.sound.hint')}</p>
  </div>
}

/** Music, foley and the room the shot's voices are heard in; the score and the location's ambience as context. */
export function SoundPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  return <InspectorSection id={sectionId(context.shot.id, 'sound')} inspector={context.inspector} shotId={context.shot.id} section="sound"
    script={context.script} draft={context.drafts.sound} save={context.save} icon={<Music size={14} />} title={t('inspector.sound.title')}
    summary={<SoundSummary context={context} />} editor={props => <SoundEditor context={context} {...props} />} />
}
