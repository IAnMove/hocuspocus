import type { TFunction } from 'i18next'
import { Package, Sparkles, Volume2 } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { SeriesScriptLine } from '../../../api/seriesShotInspector'
import { FX_CATALOG } from '../../sceneFx/types'
import { characterName, sectionId, type PartContext } from './context'
import { CheckInput, FileInput, ListEditor, NumberInput, SelectInput, TextInput } from './fields'
import { InspectorSection } from './InspectorSection'
import { grid, lineText, withField, workspaceFileUrl } from './model'
import { PlayButton } from './PlayButton'
import { useShotFiles } from './useInspectorData'

type Cue = Record<string, unknown>

const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : undefined

/** When a cue happens, in words: at a second, at a line's start or end, or when a cast member walks in. */
function cueWhen(t: TFunction<'seriesLab'>, cue: Cue, context: PartContext): string {
  const offset = number(cue.offset) ? ` ${(cue.offset as number) > 0 ? '+' : ''}${cue.offset} s` : ''
  if (cue.anchor === 'enter') {
    const cast = context.script?.cast?.[Number(cue.cast)]
    return t('inspector.when.enterOf', { name: characterName(context.series, cast?.characterId ?? cue.cast) }) + offset
  }
  if (typeof cue.line === 'number') return t(cue.anchor === 'end' ? 'inspector.when.lineEnd' : 'inspector.when.lineStart', { number: cue.line + 1 }) + offset
  return t('inspector.when.at', { seconds: number(cue.at) ?? 0 }) + offset
}

type Mode = 'at' | 'line' | 'enter'
const cueMode = (cue: Cue): Mode => cue.anchor === 'enter' ? 'enter' : typeof cue.line === 'number' ? 'line' : 'at'

/** The cue moved to another kind of moment, with that moment's defaults. */
function withMode(cue: Cue, mode: string, firstEntrance: number): Cue {
  const base: Cue = Object.fromEntries(Object.entries(cue).filter(([key]) => !['at', 'line', 'anchor', 'cast'].includes(key)))
  if (mode === 'line') return { ...base, line: 0, anchor: 'start' }
  return mode === 'enter' ? { ...base, anchor: 'enter', cast: firstEntrance } : { ...base, at: 0 }
}

/** On which line, at its start or its end. */
function LineAnchor({ cue, change, context }: { cue: Cue; change: (cue: Cue) => void; context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const lines = (context.script?.lines || []) as SeriesScriptLine[]
  return <>
    <SelectInput title={t('inspector.when.line')} value={String(cue.line ?? 0)} onChange={value => change({ ...cue, line: Number(value) })}
      options={lines.map((line, index) => ({ value: String(index), label: `#${index + 1} ${characterName(context.series, line.who)}: ${lineText(line, context.language).slice(0, 40)}` }))} />
    <SelectInput title={t('inspector.when.anchor')} value={cue.anchor === 'end' ? 'end' : 'start'} onChange={value => change({ ...cue, anchor: value })}
      options={[{ value: 'start', label: t('inspector.when.start') }, { value: 'end', label: t('inspector.when.end') }]} />
  </>
}

function WhenEditor({ cue, change, context }: { cue: Cue; change: (cue: Cue) => void; context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const entrances = (context.script?.cast || []).map((entry, index) => ({ entry, index })).filter(item => item.entry.enterFrom)
  const mode = cueMode(cue)
  const modes: Mode[] = ['at', ...(context.script?.lines?.length ? ['line' as const] : []), ...(entrances.length || mode === 'enter' ? ['enter' as const] : [])]
  return <>
    <SelectInput title={t('inspector.when.title')} value={mode} onChange={value => change(withMode(cue, value, entrances[0]?.index ?? 0))}
      options={modes.map(value => ({ value, label: t(`inspector.when.modes.${value}`) }))} />
    {mode === 'at' && <NumberInput title={t('inspector.when.seconds')} value={cue.at} min={0} max={600} onChange={value => change(withField(cue, 'at', value ?? 0))} />}
    {mode === 'line' && <LineAnchor cue={cue} change={change} context={context} />}
    {mode === 'enter' && <SelectInput title={t('inspector.when.cast')} value={String(cue.cast ?? 0)} onChange={value => change({ ...cue, cast: Number(value) })}
      options={entrances.map(item => ({ value: String(item.index), label: characterName(context.series, item.entry.characterId) }))} />}
    <NumberInput title={t('inspector.when.offset')} value={cue.offset} min={-10} max={30} onChange={value => change(withField(cue, 'offset', value))} />
  </>
}

/** Sound effects of the shot: which file, when, how loud and which part of it (in/length); each one plays here. */
export function SfxPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const files = useShotFiles(context.workspace, context.series.id, 'audio')
  const cues = (context.script?.sfx || []) as Cue[]
  return <InspectorSection id={sectionId(context.shot.id, 'sfx')} inspector={context.inspector} shotId={context.shot.id} section="sfx"
    script={context.script} draft={context.drafts.sfx} save={context.save} icon={<Volume2 size={14} />} title={t('inspector.sfx.title')}
    summary={cues.length ? null : t('inspector.sfx.empty')}
    view={cues.length > 0 && <ul className="mt-2 space-y-1">{cues.map((cue, index) => <li key={index} className="flex flex-wrap items-center gap-2 text-[11px]">
      <PlayButton url={workspaceFileUrl(context.workspace, cue.file)} label={t('inspector.sfx.play', { file: String(cue.file) })} start={number(cue.in)} length={number(cue.length)} />
      <span className="min-w-0 truncate font-mono text-text-primary">{String(cue.file)}</span>
      <span className="text-text-muted">{cueWhen(t, cue, context)} · {t('inspector.sfx.volumeShort', { volume: number(cue.volume) ?? 0.8 })}
        {number(cue.in) !== undefined || number(cue.length) !== undefined ? ` · ${t('inspector.sfx.cut', { in: number(cue.in) ?? 0, length: number(cue.length) ?? '…' })}` : ''}</span>
    </li>)}</ul>}
    editor={({ draft, change }) => <ListEditor items={(draft.sfx || []) as Cue[]} addLabel={t('inspector.sfx.add')}
      itemLabel={index => t('inspector.sfx.item', { number: index + 1 })} create={() => ({ file: files[0] || '', at: 0, volume: 0.8 })}
      onChange={items => change({ ...draft, sfx: items })}
      render={(cue, update) => <div className={grid}>
        <FileInput title={t('inspector.sfx.file')} value={cue.file} files={files} onChange={value => update({ ...cue, file: value })} />
        <WhenEditor cue={cue} change={update} context={context} />
        <NumberInput title={t('inspector.sfx.volume')} value={cue.volume} min={0} max={1} onChange={value => update(withField(cue, 'volume', value))} />
        <NumberInput title={t('inspector.sfx.in')} value={cue.in} min={0} max={600} onChange={value => update(withField(cue, 'in', value))} />
        <NumberInput title={t('inspector.sfx.length')} value={cue.length} min={0.05} max={60} onChange={value => update(withField(cue, 'length', value))} />
        <div className="flex items-end"><PlayButton url={workspaceFileUrl(context.workspace, cue.file)} label={t('inspector.sfx.play', { file: String(cue.file) })}
          start={number(cue.in)} length={number(cue.length)} text={t('inspector.sfx.listen')} /></div>
      </div>} />} />
}

const FX_KINDS = FX_CATALOG.map(item => item.id)

/** Screen effects drawn over the frame (fog, light rays, an impact flash...), timed like the sounds. */
export function FxPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const cues = (context.script?.fx || []) as Cue[]
  const length = (cue: Cue) => cue.duration === 'shot' ? t('inspector.fx.toEnd') : t('inspector.fx.lasts', { seconds: number(cue.duration) ?? 1 })
  return <InspectorSection id={sectionId(context.shot.id, 'fx')} inspector={context.inspector} shotId={context.shot.id} section="fx"
    script={context.script} draft={context.drafts.fx} save={context.save} icon={<Sparkles size={14} />} title={t('inspector.fx.title')}
    summary={cues.length ? <ul className="flex flex-wrap gap-1.5">{cues.map((cue, index) => <li key={index}
      className="rounded-full border border-border bg-bg-primary px-2 py-0.5">{String(cue.kind)} · {cueWhen(t, cue, context)} · {length(cue)}
      {number(cue.intensity) !== undefined ? ` · ${t('inspector.fx.intensityShort', { value: cue.intensity })}` : ''}</li>)}</ul> : t('inspector.fx.empty')}
    editor={({ draft, change }) => <ListEditor items={(draft.fx || []) as Cue[]} addLabel={t('inspector.fx.add')}
      itemLabel={index => t('inspector.fx.item', { number: index + 1 })} create={() => ({ kind: FX_KINDS[0], at: 0, duration: 1 })}
      onChange={items => change({ ...draft, fx: items })}
      render={(cue, update) => <div className={grid}>
        <SelectInput title={t('inspector.fx.kind')} value={cue.kind} onChange={value => update({ ...cue, kind: value })}
          options={FX_KINDS.map(value => ({ value, label: value }))} />
        <WhenEditor cue={cue} change={update} context={context} />
        <CheckInput title={t('inspector.fx.toEnd')} value={cue.duration === 'shot'} onChange={value => update({ ...cue, duration: value ? 'shot' : 1 })} />
        {cue.duration !== 'shot' && <NumberInput title={t('inspector.fx.duration')} value={cue.duration} min={0.1} max={30}
          onChange={value => update(withField(cue, 'duration', value))} />}
        <NumberInput title={t('inspector.fx.intensity')} value={cue.intensity} min={0.1} max={2} onChange={value => update(withField(cue, 'intensity', value))} />
        <NumberInput title="x %" value={cue.x} min={0} max={100} step={1} onChange={value => update(withField(cue, 'x', value))} />
        <NumberInput title="y %" value={cue.y} min={0} max={100} step={1} onChange={value => update(withField(cue, 'y', value))} />
        <NumberInput title={t('inspector.fx.size')} value={cue.size} min={1} max={200} step={1} onChange={value => update(withField(cue, 'size', value))} />
        <TextInput title={t('inspector.fx.color')} value={cue.color} placeholder="#ffcc00" onChange={value => update(withField(cue, 'color', value))} />
      </div>} />} />
}

/** Props on the set: an image placed at x/y % (or stood on the floor), at a scale. */
export function PropsPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const files = useShotFiles(context.workspace, context.series.id, 'image')
  const props = (context.script?.props || []) as Cue[]
  return <InspectorSection id={sectionId(context.shot.id, 'props')} inspector={context.inspector} shotId={context.shot.id} section="props"
    script={context.script} draft={context.drafts.props} save={context.save} icon={<Package size={14} />} title={t('inspector.props.title')}
    summary={props.length ? null : t('inspector.props.empty')}
    view={props.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{props.map((prop, index) => <li key={index}
      className="flex items-center gap-2 rounded-lg border border-border bg-bg-primary p-1.5 text-[10px] text-text-secondary">
      {typeof prop.file === 'string' && <img src={workspaceFileUrl(context.workspace, prop.file)} alt="" loading="lazy" className="h-10 w-10 rounded object-contain" />}
      <span><span className="block font-mono text-text-primary">{String(prop.file || prop.assetId)}</span>
        {prop.ground ? t('inspector.props.onFloor', { x: number(prop.x) ?? 50 }) : t('inspector.props.at', { x: number(prop.x) ?? 50, y: number(prop.y) ?? 50 })} · ×{number(prop.scale) ?? 0.3}</span>
    </li>)}</ul>}
    editor={({ draft, change }) => <ListEditor items={(draft.props || []) as Cue[]} addLabel={t('inspector.props.add')}
      itemLabel={index => t('inspector.props.item', { number: index + 1 })} create={() => ({ file: files[0] || '', x: 50, y: 70, scale: 0.3 })}
      onChange={items => change({ ...draft, props: items })}
      render={(prop, update) => <div className={grid}>
        <FileInput title={t('inspector.props.file')} value={prop.file} files={files} onChange={value => update({ ...withField(prop, 'assetId', undefined), file: value })} />
        <NumberInput title="x %" value={prop.x} min={-50} max={150} step={1} onChange={value => update(withField(prop, 'x', value))} />
        <NumberInput title="y %" value={prop.y} min={-50} max={150} step={1} onChange={value => update(withField(prop, 'y', value))} />
        <NumberInput title={t('inspector.props.scale')} value={prop.scale} min={0.01} max={4} onChange={value => update(withField(prop, 'scale', value))} />
        <CheckInput title={t('inspector.props.ground')} value={prop.ground} onChange={value => update(withField(prop, 'ground', value || undefined))} />
      </div>} />} />
}
