import { useState } from 'react'
import { Check, ImagePlus, Layers, MapPin } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { seriesAssetUrl, type SeriesReferenceImport } from '../referenceImages'
import { SeriesReferenceGenerator } from '../SeriesReferenceGenerator'
import { secondaryButton } from '../styles'
import type { SeriesProject } from '../types'
import { sectionId, type PartContext } from './context'
import { CheckInput, FileInput, ListEditor, NumberInput, SelectInput } from './fields'
import { InspectorSection, type DraftProps } from './InspectorSection'
import { grid, planBackground, withField, workspaceFileUrl } from './model'
import { useShotFiles } from './useInspectorData'

type Layer = Record<string, unknown>

export interface SeriesEdits {
  updateSeries: (updater: (series: SeriesProject) => SeriesProject) => void
  saveNow: () => Promise<unknown>
  onAssetImported: (workspace: string, result: SeriesReferenceImport) => void
}

function LayerEditor({ layer, change, files }: { layer: Layer; change: (layer: Layer) => void; files: string[] }) {
  const { t } = useUiTranslation('seriesLab')
  const video = typeof layer.file === 'string' && /\.(mp4|webm|mov)$/i.test(layer.file)
  return <div className={grid}>
    <FileInput title={t('inspector.set.layerFile')} value={layer.file} files={files} onChange={value => change({ ...withField(layer, 'assetId', undefined), file: value })} />
    <NumberInput title={t('inspector.set.depth')} value={layer.depth} min={0} max={1} onChange={value => change(withField(layer, 'depth', value))} />
    <CheckInput title={t('inspector.set.front')} value={layer.front} onChange={value => change({ ...layer, front: value })} />
    <NumberInput title={t('inspector.set.opacity')} value={layer.opacity} min={0} max={1} onChange={value => change(withField(layer, 'opacity', value))} />
    <NumberInput title="x %" value={layer.x} min={-50} max={150} step={1} onChange={value => change(withField(layer, 'x', value))} />
    <NumberInput title="y %" value={layer.y} min={-50} max={150} step={1} onChange={value => change(withField(layer, 'y', value))} />
    <NumberInput title={t('inspector.set.scale')} value={layer.scale} min={0.05} max={4} onChange={value => change(withField(layer, 'scale', value))} />
    <NumberInput title={t('inspector.set.drift')} value={layer.drift} min={-400} max={400} step={1} onChange={value => change(withField(layer, 'drift', value))} />
    {video && <>
      <NumberInput title={t('inspector.set.start')} value={layer.start} min={0} max={3600} onChange={value => change(withField(layer, 'start', value))} />
      <SelectInput title={t('inspector.set.loop')} value={layer.loop} empty={t('inspector.set.loops.restart')} onChange={value => change(withField(layer, 'loop', value))}
        options={(['loop', 'hold', 'pingpong'] as const).map(value => ({ value, label: t(`inspector.set.loops.${value}`) }))} />
      <NumberInput title={t('inspector.set.speed')} value={layer.speed} min={0.1} max={4} onChange={value => change(withField(layer, 'speed', value))} />
    </>}
  </div>
}

/** The location's background: its images, one of them used for every shot there, or a new one generated. */
function Background({ context, edits }: { context: PartContext; edits: SeriesEdits }) {
  const { t } = useUiTranslation('seriesLab')
  const [generating, setGenerating] = useState(false)
  const location = context.series.locations.find(item => item.id === context.shot.locationId)
  if (!location) return null
  const current = planBackground(context.series, context.shot)
  const images = [...new Set([...location.referenceAssetIds, ...location.variants.flatMap(item => item.referenceAssetIds)])]
    .map(id => context.series.assets[id]).filter(asset => asset && ['image', 'location'].includes(asset.kind) && !asset.isDerivedThumbnail)
  const chosen = location.layout2d?.backgroundAssetId
  const shots = context.episode.shots.filter(item => item.locationId === location.id).length
  const use = (assetId: string) => {
    edits.updateSeries(series => ({ ...series, locations: series.locations.map(item => item.id === location.id
      ? { ...item, layout2d: { ...item.layout2d, backgroundAssetId: assetId } } : item) }))
    void edits.saveNow()
  }
  return <div className="mt-2 space-y-2 rounded-lg border border-border bg-bg-primary p-2">
    <div className="flex flex-wrap items-center gap-2">
      {current && <img src={current.url} alt="" loading="lazy" className="aspect-video w-32 rounded object-cover" />}
      <p className="min-w-0 flex-1 text-[10px] text-text-muted">{t(location.layout2d?.plateAssetId ? 'inspector.set.plateActive' : 'inspector.set.backgroundHint', { count: shots })}</p>
      <button type="button" className={`${secondaryButton} min-h-10 sm:min-h-0 sm:py-1`} aria-expanded={generating} onClick={() => setGenerating(value => !value)}>
        <ImagePlus size={13} />{t('inspector.set.generate')}</button>
    </div>
    {images.length > 1 && <ul aria-label={t('inspector.set.images')} className="flex gap-2 overflow-x-auto pb-1">{images.map(asset => <li key={asset!.id} className="shrink-0">
      <button type="button" className={`relative block overflow-hidden rounded border ${asset!.id === chosen ? 'border-violet-400' : 'border-border'}`}
        aria-label={t('inspector.set.useImage')} aria-pressed={asset!.id === chosen} onClick={() => use(asset!.id)}>
        <img src={seriesAssetUrl(asset!)} alt="" loading="lazy" className="aspect-video w-24 object-cover" />
        {asset!.id === chosen && <Check size={14} className="absolute right-1 top-1 rounded-full bg-violet-600 p-0.5 text-white" />}
      </button></li>)}</ul>}
    {generating && <SeriesReferenceGenerator workspace={context.workspace} series={context.series} target={{ kind: 'location', id: location.id }}
      saveNow={edits.saveNow} onImported={(workspace, result) => { edits.onAssetImported(workspace, result); use(result.asset.id); setGenerating(false) }} />}
  </div>
}

function LayerChip({ workspace, layer }: { workspace: string; layer: Layer }) {
  const { t } = useUiTranslation('seriesLab')
  const image = typeof layer.file === 'string' && /\.(png|webp|jpe?g)$/i.test(layer.file)
  return <li className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-primary p-1 text-[10px] text-text-secondary">
    <Layers size={12} />{image && <img src={workspaceFileUrl(workspace, layer.file)} alt="" loading="lazy" className="h-8 w-8 rounded object-contain" />}
    <span className="font-mono">{String(layer.file || layer.assetId)}</span>
    <span className="text-text-muted">{t('inspector.set.layerShort', { depth: layer.depth ?? '—', side: t(layer.front ? 'inspector.set.inFront' : 'inspector.set.behind') })}</span>
  </li>
}

/** The location, its set layers (the shot's own or the location's) and the background, as the shot uses them. */
function setFacts(context: PartContext) {
  const script = context.script
  const location = context.series.locations.find(item => item.id === (script?.location || context.shot.locationId))
  const own = Array.isArray(script?.layers)
  return { location, variant: location?.variants.find(item => item.id === script?.variant), own,
    layers: (own ? script!.layers : location?.layout2d?.layers || []) as Layer[], twoD: context.shot.productionMethod === 'animation_2d' }
}

function SetSummary({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const { location, variant, own, layers, twoD } = setFacts(context)
  const depth = context.script?.castDepth
  return <span>{[location?.name || context.script?.location || '—', variant?.label,
    twoD ? t(own ? 'inspector.set.ownLayers' : 'inspector.set.locationLayers', { count: layers.length }) : '',
    typeof depth === 'number' ? t('inspector.set.castDepthShort', { value: depth }) : ''].filter(Boolean).join(' · ')}</span>
}

function SetView({ context, edits }: { context: PartContext; edits: SeriesEdits }) {
  const { layers, twoD } = setFacts(context)
  if (!twoD) return null
  return <>
    {layers.length > 0 && <ul className="mt-2 flex flex-wrap gap-1.5">{layers.map((layer, index) => <LayerChip key={index} workspace={context.workspace} layer={layer} />)}</ul>}
    <Background context={context} edits={edits} />
  </>
}

function SetEditor({ context, draft, change }: DraftProps & { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const files = useShotFiles(context.workspace, context.series.id, 'image')
  const videos = useShotFiles(context.workspace, context.series.id, 'video')
  const chosen = context.series.locations.find(item => item.id === draft.location)
  const twoD = context.shot.productionMethod === 'animation_2d'
  const variants = chosen?.variants || []
  return <div className="space-y-2">
    <div className={grid}>
      <SelectInput title={t('inspector.set.location')} value={draft.location} onChange={value => change({ ...withField(draft, 'variant', undefined), location: value })}
        options={context.series.locations.map(item => ({ value: item.id, label: item.name }))} />
      {variants.length > 0 && <SelectInput title={t('inspector.set.variant')} value={draft.variant} empty={t('inspector.set.noVariant')}
        onChange={value => change(withField(draft, 'variant', value))} options={variants.map(item => ({ value: item.id, label: item.label }))} />}
      {twoD && <NumberInput title={t('inspector.set.castDepth')} value={draft.castDepth} min={0.1} max={1} onChange={value => change(withField(draft, 'castDepth', value))} />}
    </div>
    {twoD && <OwnLayers draft={draft} change={change} locationLayers={chosen?.layout2d?.layers} files={[...files, ...videos]} />}
  </div>
}

/** The shot's own set layers instead of its location's (an empty list turns them off), edited as a list. */
function OwnLayers({ draft, change, locationLayers, files }: DraftProps & { locationLayers?: unknown[]; files: string[] }) {
  const { t } = useUiTranslation('seriesLab')
  const own = Array.isArray(draft.layers)
  return <>
    <CheckInput title={t('inspector.set.useOwnLayers')} value={own}
      onChange={value => change(value ? { ...draft, layers: structuredClone(locationLayers || []) } : withField(draft, 'layers', undefined))} />
    {own ? <ListEditor items={draft.layers as Layer[]} addLabel={t('inspector.set.addLayer')} itemLabel={index => t('inspector.set.layer', { number: index + 1 })}
      create={() => ({ file: files[0] || '', depth: 0.3, front: false, opacity: 1, x: 50, y: 50, scale: 1 })}
      onChange={items => change({ ...draft, layers: items })}
      render={(layer, update) => <LayerEditor layer={layer} change={update} files={files} />} />
      : <p className="text-[10px] text-text-muted">{t('inspector.set.locationLayersHint')}</p>}
  </>
}

/** Where the shot happens: the location (and variant), its background, and the set layers drawn around the cast. */
export function SetPart({ context, edits }: { context: PartContext; edits: SeriesEdits }) {
  const { t } = useUiTranslation('seriesLab')
  return <InspectorSection id={sectionId(context.shot.id, 'set')} inspector={context.inspector} shotId={context.shot.id} section="set"
    script={context.script} draft={context.drafts.set} save={context.save} icon={<MapPin size={14} />} title={t('inspector.set.title')}
    summary={<SetSummary context={context} />} view={<SetView context={context} edits={edits} />}
    editor={props => <SetEditor context={context} {...props} />} />
}
