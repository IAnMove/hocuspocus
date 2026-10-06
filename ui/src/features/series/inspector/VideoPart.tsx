import type { TFunction } from 'i18next'
import { useEffect, useState, type ReactNode } from 'react'
import { Clapperboard, Loader2, Upload } from 'lucide-react'
import * as api from '../../../api/client'
import { useUiTranslation } from '../../../i18n'
import { ensureUploadsPath } from '../../../lib/labsImagePick'
import { useSeriesStore } from '../store'
import { secondaryButton } from '../styles'
import { sectionId, type PartContext } from './context'
import { FileInput, NumberInput, SelectInput } from './fields'
import { InspectorSection, type DraftProps } from './InspectorSection'
import { grid, shotTakes, withField } from './model'
import { useShotFiles } from './useInspectorData'

interface Generation { prompt?: string; startFrame?: string; model?: string; seed?: string }

const fileName = (value: unknown) => typeof value === 'string' && value ? value.split(/[\\/]/).pop() || '' : ''

/** How the source clip was generated, from its sidecar: the prompt, the start frame, the model and seed. */
function useGeneration(workspace: string, source: string | undefined) {
  const [found, setFound] = useState<{ source: string; value: Generation }>()
  useEffect(() => {
    if (!source) return
    let alive = true
    api.fetchOutputMetadata(source, workspace).then(metadata => {
      const params = ((metadata as { params?: Record<string, unknown> }).params || {}) as Record<string, unknown>
      if (alive) setFound({ source, value: { prompt: typeof params.prompt === 'string' ? params.prompt : undefined,
        startFrame: fileName(params.image_start) || undefined, model: typeof params.model_type === 'string' ? params.model_type : undefined,
        seed: params.seed !== undefined ? String(params.seed) : undefined } })
    }).catch(() => { if (alive) setFound({ source, value: {} }) })
    return () => { alive = false }
  }, [workspace, source])
  return found && found.source === source ? found.value : undefined
}

/** One fact of the clip, as a definition-list row. */
function Fact({ title, children, mono }: { title: string; children: ReactNode; mono?: boolean }) {
  return <><dt className="text-text-muted">{title}</dt><dd className={mono ? 'font-mono text-text-primary' : 'whitespace-pre-wrap text-text-secondary'}>{children}</dd></>
}

/** What made the clip: its source file, the generator, whether it has its own sound, the prompt, start frame and seed. */
function ClipFacts({ workspace, metadata, source, generation }: {
  workspace: string; metadata: Record<string, unknown>; source?: string; generation?: Generation
}) {
  const { t } = useUiTranslation('seriesLab')
  const sound = typeof metadata.has_audio === 'boolean' ? t(metadata.has_audio ? 'inspector.video.yes' : 'inspector.video.no') : ''
  const generator = typeof metadata.generator === 'string' ? metadata.generator : ''
  return <dl className="grid gap-x-3 gap-y-1 @md:grid-cols-[8rem_1fr]">
    {source && <Fact title={t('inspector.video.source')} mono>{source}</Fact>}
    {generator && <Fact title={t('inspector.video.generator')}>{generator}</Fact>}
    {sound && <Fact title={t('inspector.video.ownSound')}>{sound}</Fact>}
    {generation?.prompt && <Fact title={t('inspector.video.prompt')}>{generation.prompt}</Fact>}
    {generation?.startFrame && <Fact title={t('inspector.video.startFrame')}>
      <img src={api.getFileUrl(generation.startFrame, workspace)} alt={generation.startFrame} loading="lazy" className="aspect-video w-40 rounded object-cover" /></Fact>}
    {generation?.seed && <Fact title={t('inspector.video.seed')}>{[generation.seed, generation.model].filter(Boolean).join(' · ')}</Fact>}
  </dl>
}

/** Another workspace clip as the shot's new take (to approve). */
function ReplaceClip({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const [file, setFile] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const videos = useShotFiles(context.workspace, context.series.id, 'video')
  const importTake = async () => {
    setBusy(true); setError('')
    try {
      await useSeriesStore.getState().saveNow()
      const uploaded = await ensureUploadsPath({ name: file, type: 'video', mode: null, size: 0, created_at: 0, url: api.getFileUrl(file, context.workspace) })
      const result = await api.importSeriesAsset(context.workspace, context.series.id, { uploadPath: uploaded.path, name: file, ownerType: 'shot',
        ownerId: context.shot.id, kind: 'video', asTake: true, metadata: { productionMethod: context.shot.productionMethod || 'imported_video', source: file } })
      useSeriesStore.getState().acceptAssetImport(context.workspace, result)
      setFile('')
    } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  return <>
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-bg-primary p-2">
      <div className="min-w-48 flex-1"><FileInput title={t('inspector.video.replace')} value={file} files={videos} onChange={setFile} /></div>
      <button type="button" className={`${secondaryButton} min-h-10 sm:min-h-0 sm:py-1.5`} disabled={busy || !file} onClick={() => void importTake()}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}{t('inspector.video.import')}</button>
    </div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </>
}

function ClipSoundEditor({ draft, change }: DraftProps) {
  const { t } = useUiTranslation('seriesLab')
  return <div className={grid}>
    <SelectInput title={t('inspector.video.audioTitle')} value={draft.clipAudio || 'keep'} onChange={value => change({ ...draft, clipAudio: value })}
      options={(['keep', 'drop'] as const).map(value => ({ value, label: t(`inspector.video.audio.${value}`) }))} />
    <NumberInput title={t('inspector.video.volume')} value={draft.clipVolume} min={0} max={2} onChange={value => change(withField(draft, 'clipVolume', value))} />
    <SelectInput title={t('inspector.video.fitTitle')} value={draft.clipFit} empty={t('inspector.video.fit.auto')} onChange={value => change(withField(draft, 'clipFit', value))}
      options={(['cover', 'contain'] as const).map(value => ({ value, label: t(`inspector.video.fit.${value}`) }))} />
  </div>
}

/** How the clip's own sound plays at the cut, in words. */
function clipSound(t: TFunction<'seriesLab'>, script: PartContext['script'], method: string): string {
  return [t(`production.methods.${method === 'imported_video' ? 'imported_video' : 'generated_video'}`), t(`inspector.video.audio.${script?.clipAudio === 'drop' ? 'drop' : 'keep'}`),
    typeof script?.clipVolume === 'number' ? t('inspector.video.volumeShort', { volume: script.clipVolume }) : '',
    script?.clipFit === 'cover' || script?.clipFit === 'contain' ? t(`inspector.video.fit.${script.clipFit}`) : ''].filter(Boolean).join(' · ')
}

/** A generated (H3) or imported clip: what made it, how its own sound plays at the cut, and a new clip as its take. */
export function VideoPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  const take = shotTakes(context.series, context.shot)[0]
  const metadata = take?.asset.metadata || {}
  const source = typeof metadata.source === 'string' ? metadata.source : undefined
  const generation = useGeneration(context.workspace, source)
  return <InspectorSection id={sectionId(context.shot.id, 'video')} inspector={context.inspector} shotId={context.shot.id} section="video"
    script={context.script} draft={context.drafts.video} save={context.save} icon={<Clapperboard size={14} />} title={t('inspector.video.title')}
    summary={clipSound(t, context.script, context.shot.productionMethod || 'generated_video')}
    view={<div className="mt-2 space-y-2 text-[11px]">
      {take ? <ClipFacts workspace={context.workspace} metadata={metadata} source={source} generation={generation} />
        : <p className="text-text-muted">{t('inspector.video.noTake')}</p>}
      {source && generation && !generation.prompt && <p className="text-[10px] text-text-muted">{t('inspector.video.noRecipe')}</p>}
      <ReplaceClip context={context} />
      <p className="text-[10px] text-text-muted">{t('inspector.video.hint')}</p>
    </div>}
    editor={props => <ClipSoundEditor {...props} />} />
}
