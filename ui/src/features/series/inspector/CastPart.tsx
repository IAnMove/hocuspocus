import type { TFunction } from 'i18next'
import { Smile, Users } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { characterKitPoseOptions } from '../../characters/characterKitGuide'
import { secondaryButton } from '../styles'
import type { SeriesShotScene3D } from '../types'
import { characterKit, characterName, sectionId, type PartContext } from './context'
import { ListEditor, NumberInput, SelectInput } from './fields'
import { InspectorSection } from './InspectorSection'
import { grid, stableJson, withField } from './model'

type Entry = Record<string, unknown> & { characterId?: string; poseId?: string }

function poseOptions(context: PartContext) {
  return (characterId: unknown) => {
    const kit = characterKit(context.series, context.kits, characterId)
    return kit ? characterKitPoseOptions(kit).map(pose => ({ value: pose.id, label: pose.label, source: pose.source })) : []
  }
}

/** One cast member on screen: the pose drawing, name, pose and where it stands, with a link to its face rig. */
function Figure({ context, entry, onOpenFaceRig, place }: {
  context: PartContext; entry: Entry; onOpenFaceRig?: (characterId: string, poseId?: string) => void; place?: string
}) {
  const { t } = useUiTranslation('seriesLab')
  const poses = poseOptions(context)(entry.characterId)
  const pose = poses.find(item => item.value === (entry.poseId || 'base')) || poses[0]
  const name = characterName(context.series, entry.characterId)
  return <li className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-bg-primary p-1.5">
    {pose?.source ? <img src={pose.source} alt="" loading="lazy" className="h-12 w-10 shrink-0 rounded object-contain" /> : <span className="h-12 w-10 shrink-0 rounded bg-bg-tertiary" />}
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[11px] font-semibold text-text-primary">{name}</span>
      <span className="block truncate text-[10px] text-text-muted">{[pose?.label || entry.poseId || t('inspector.cast.basePose'), place].filter(Boolean).join(' · ')}</span>
    </span>
    {onOpenFaceRig && typeof entry.characterId === 'string' && <button type="button" className={`${secondaryButton} min-h-10 px-2 sm:min-h-0 sm:py-1`}
      aria-label={t('inspector.cast.open', { name })} title={t('inspector.cast.open', { name })}
      onClick={() => onOpenFaceRig(entry.characterId as string, entry.poseId)}><Smile size={13} /><span className="hidden sm:inline">{t('inspector.cast.openShort')}</span></button>}
  </li>
}

const SIDES = ['left', 'right'] as const
const side = (value: unknown) => SIDES.find(item => item === value)

function place(t: TFunction<'seriesLab'>, entry: Entry): string {
  const from = side(entry.enterFrom)
  const parts = [typeof entry.x === 'number' ? t('inspector.cast.at', { x: Math.round(entry.x) }) : '',
    from ? t('inspector.cast.enters', { side: t(`inspector.cast.sides.${from}`) }) : '']
  return parts.filter(Boolean).join(' · ')
}

function CastEntryEditor({ context, entry, change }: { context: PartContext; entry: Entry; change: (entry: Entry) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const poses = poseOptions(context)(entry.characterId)
  return <div className={grid}>
    <SelectInput title={t('inspector.cast.character')} value={entry.characterId} onChange={value => change({ ...withField(entry, 'poseId', undefined), characterId: value })}
      options={context.series.characters.map(item => ({ value: item.id, label: item.name }))} />
    <SelectInput title={t('inspector.cast.pose')} value={entry.poseId} empty={t('inspector.cast.basePose')}
      onChange={value => change(withField(entry, 'poseId', value))} options={poses.filter(pose => pose.value !== 'base')} />
    <NumberInput title={t('inspector.cast.x')} value={entry.x} min={-50} max={150} step={1} onChange={value => change(withField(entry, 'x', value))} />
    <NumberInput title={t('inspector.cast.scale')} value={entry.scale} min={0.2} max={4} step={0.05} onChange={value => change(withField(entry, 'scale', value))} />
    <SelectInput title={t('inspector.cast.motion')} value={entry.motion} empty={t('inspector.cast.motions.idle')}
      onChange={value => change(withField(entry, 'motion', value))} options={(['still', 'shake'] as const).map(value => ({ value, label: t(`inspector.cast.motions.${value}`) }))} />
    <SelectInput title={t('inspector.cast.enterFrom')} value={entry.enterFrom} empty={t('inspector.cast.noEntrance')}
      onChange={value => change(withField(entry, 'enterFrom', value))} options={SIDES.map(value => ({ value, label: t(`inspector.cast.sides.${value}`) }))} />
    {Boolean(entry.enterFrom) && <>
      <NumberInput title={t('inspector.cast.enterAt')} value={entry.enterAt} min={0} max={600} onChange={value => change(withField(entry, 'enterAt', value))} />
      <NumberInput title={t('inspector.cast.enterDuration')} value={entry.enterDuration} min={0.1} max={60} onChange={value => change(withField(entry, 'enterDuration', value))} />
      <SelectInput title={t('inspector.cast.enterGait')} value={entry.enterGait} empty={t('inspector.cast.gaits.slide')}
        onChange={value => change(withField(entry, 'enterGait', value))} options={(['hop', 'walk'] as const).map(value => ({ value, label: t(`inspector.cast.gaits.${value}`) }))} />
    </>}
  </div>
}

/** Characters on screen in a 2D shot: who, pose, position and entrance; each opens in its Character Kit / face rig. */
export function CastPart({ context, onOpenFaceRig }: { context: PartContext; onOpenFaceRig?: (characterId: string, poseId?: string) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const cast = (context.script?.cast || []) as Entry[]
  return <InspectorSection id={sectionId(context.shot.id, 'cast')} inspector={context.inspector} shotId={context.shot.id} section="cast"
    script={context.script} draft={context.drafts.cast} save={context.save} icon={<Users size={14} />} title={t('inspector.cast.title')}
    summary={cast.length ? null : t('inspector.cast.empty')}
    view={cast.length > 0 && <ul className="mt-2 grid gap-1.5 @md:grid-cols-2">{cast.map((entry, index) =>
      <Figure key={`${index}-${entry.characterId}`} context={context} entry={entry} onOpenFaceRig={onOpenFaceRig} place={place(t, entry)} />)}</ul>}
    editor={({ draft, change }) => <ListEditor items={(draft.cast || []) as Entry[]} max={8} addLabel={t('inspector.cast.add')}
      itemLabel={index => t('inspector.cast.item', { number: index + 1 })}
      create={() => ({ characterId: context.series.characters[0]?.id || '', x: 50 })}
      onChange={items => change({ ...draft, cast: items })}
      render={(entry, update) => <CastEntryEditor context={context} entry={entry} change={update} />} />} />
}

type Cast3D = NonNullable<SeriesShotScene3D['cast']>

/** Characters of a 3D shot: each speaks through one object of the scene, drawn as its Character Kit pose. */
export function Cast3DPart({ context, onOpenFaceRig }: { context: PartContext; onOpenFaceRig?: (characterId: string, poseId?: string) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const options = poseOptions(context)
  const cast = (context.script?.scene3d?.cast || []) as Cast3D
  return <InspectorSection id={sectionId(context.shot.id, 'cast3d')} inspector={context.inspector} shotId={context.shot.id} section="cast3d"
    script={context.script} draft={context.drafts.cast3d} save={context.save} icon={<Users size={14} />} title={t('inspector.cast.title')}
    summary={cast.length ? t('inspector.cast.hint3d') : t('inspector.cast.empty3d')}
    slice={script => ({ cast: structuredClone(script?.scene3d?.cast || []) })}
    diff={(draft, script) => stableJson(draft.cast) === stableJson(script?.scene3d?.cast || [])
      ? null : { scene3d: { ...script?.scene3d, cast: draft.cast } }}
    editable={cast.length > 0}
    view={cast.length > 0 && <ul className="mt-2 grid gap-1.5 @md:grid-cols-2">{cast.map(entry =>
      <Figure key={entry.objectId} context={context} entry={entry} onOpenFaceRig={onOpenFaceRig} place={t('inspector.cast.object', { id: entry.objectId })} />)}</ul>}
    editor={({ draft, change }) => <div className="space-y-2">{((draft.cast || []) as Cast3D).map((entry, index) =>
      <div key={entry.objectId || index} className="grid grid-cols-2 gap-2">
        <p className="self-center text-[11px] text-text-secondary">{characterName(context.series, entry.characterId)} · {t('inspector.cast.object', { id: entry.objectId })}</p>
        <SelectInput title={t('inspector.cast.pose')} value={entry.poseId} empty={t('inspector.cast.basePose')}
          options={options(entry.characterId).filter(pose => pose.value !== 'base')}
          onChange={value => change({ ...draft, cast: ((draft.cast || []) as Cast3D).map((item, position) => position === index ? withField(item, 'poseId', value) : item) })} />
      </div>)}</div>} />
}
