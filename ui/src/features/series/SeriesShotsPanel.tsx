import { useMemo, useState } from 'react'
import { CheckSquare, RefreshCw, Square, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { Pill, SectionCard } from './components'
import { inputClass, primaryButton, secondaryButton, selectClass, textareaClass } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

export function SeriesShotsPanel({
  workspace, series, episode, updateEpisode, replaceSeries, saveNow, onRender,
}: {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  updateEpisode: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  replaceSeries: (series: SeriesProject) => void
  saveNow: () => Promise<unknown>
  onRender: (mode: 'selected' | 'missing' | 'failed' | 'all', shotIds?: string[]) => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [routing, setRouting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const characters = useMemo(() => Object.fromEntries(series.characters.map(item => [item.id, item.name])), [series.characters])
  const locations = useMemo(() => Object.fromEntries(series.locations.map(item => [item.id, item.name])), [series.locations])
  const patchShot = (shotId: string, updater: (shot: SeriesShot) => SeriesShot) => updateEpisode(current => ({
    ...current, shots: current.shots.map(shot => shot.id === shotId ? updater(shot) : shot),
  }))
  const routeAll = async () => {
    setRouting(true); setError(null)
    try {
      await saveNow()
      const result = await api.routeSeriesReferences(workspace, series.id, episode.id)
      const manifests = result.manifests || {}
      updateEpisode(current => ({
        ...current,
        shots: current.shots.map(shot => manifests[shot.id] ? { ...shot, referenceManifest: manifests[shot.id] } : shot),
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setRouting(false) }
  }
  const routeOne = async (shotId: string) => {
    setRouting(true); setError(null)
    try {
      await saveNow()
      const result = await api.routeSeriesReferences(workspace, series.id, episode.id, shotId)
      if (result.manifest) patchShot(shotId, shot => ({ ...shot, referenceManifest: result.manifest }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setRouting(false) }
  }
  const uploadComposedFrame = async (
    shot: SeriesShot, file: File, referenceRole: 'composed_start_frame' | 'composed_end_frame',
  ) => {
    setRouting(true); setError(null)
    try {
      await saveNow()
      const upload = await api.uploadImage(file)
      const result = await api.importSeriesAsset(workspace, series.id, {
        uploadPath: upload.path, name: file.name, ownerType: 'shot', ownerId: shot.id,
        kind: 'image', referenceRole,
      })
      replaceSeries(result.series)
      const routed = await api.routeSeriesReferences(workspace, series.id, episode.id, shot.id)
      if (routed.manifest) patchShot(shot.id, current => ({ ...current, referenceManifest: routed.manifest }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setRouting(false) }
  }
  const totalDuration = episode.shots.reduce((sum, shot) => sum + shot.durationSeconds, 0)
  return <div className="space-y-4 pb-10">
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
    <SectionCard title="Shot breakdown" description={`${episode.shots.length} shots · ${totalDuration.toFixed(1)}s planned · exact ID routing before render`} action={<button className={secondaryButton} disabled={routing || !episode.shots.length} onClick={() => void routeAll()}><RefreshCw size={13} className={routing ? 'animate-spin' : ''} />Route all references</button>}>
      <div className="mb-3 flex flex-wrap gap-2"><button className={primaryButton} disabled={!selected.size} onClick={() => onRender('selected', [...selected])}><CheckSquare size={13} />Render selected ({selected.size})</button><button className={secondaryButton} onClick={() => onRender('missing')}>Render missing</button><button className={secondaryButton} onClick={() => onRender('failed')}>Retry failed</button><button className={secondaryButton} onClick={() => onRender('all')}>Render all unapproved</button></div>
      {!episode.shots.length && <p className="rounded-lg border border-violet-500/30 bg-violet-500/10 p-4 text-xs text-violet-200">Generate and apply a complete episode proposal to create the 8–12 shot plan.</p>}
      <div className="space-y-3">{episode.shots.map(shot => {
        const manifest = shot.referenceManifest
        const approved = shot.attempts.find(item => item.id === shot.approvedAttemptId)
        return <article key={shot.id} id={`series-shot-${shot.id}`} className="rounded-xl border border-border bg-bg-primary p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded border border-dashed border-border bg-bg-tertiary text-[8px] uppercase text-text-muted">Shot {shot.order}<br />poster</div>
            <button onClick={() => setSelected(current => { const next = new Set(current); if (next.has(shot.id)) next.delete(shot.id); else next.add(shot.id); return next })}>{selected.has(shot.id) ? <CheckSquare size={16} className="text-violet-400" /> : <Square size={16} className="text-text-muted" />}</button>
            <Pill tone="blue">#{shot.order}</Pill><strong className="text-xs text-text-primary">{shot.framing || 'Shot'}</strong><Pill>{shot.durationSeconds}s</Pill>
            {shot.primarySpeakerId && <Pill tone="violet">Speaker · {characters[shot.primarySpeakerId] || shot.primarySpeakerId}</Pill>}
            {shot.locationId && <Pill>{locations[shot.locationId] || shot.locationId}</Pill>}
            {approved && <Pill tone="green">Approved · {approved.model}</Pill>}
            <button className={`ml-auto ${secondaryButton}`} disabled={routing} onClick={() => void routeOne(shot.id)}><RefreshCw size={12} />Re-route</button>
          </div>
          <div className="mt-3 grid gap-2 lg:grid-cols-[120px_120px_1fr]">
            <input className={inputClass} type="number" min={1} max={30} value={shot.durationSeconds} onChange={event => patchShot(shot.id, current => ({ ...current, durationSeconds: Number(event.target.value), referenceManifest: undefined }))} />
            <select className={selectClass} value={shot.renderStrategy} onChange={event => patchShot(shot.id, current => ({ ...current, renderStrategy: event.target.value as SeriesShot['renderStrategy'], referenceManifest: undefined }))}><option value="auto">Auto</option><option value="direct">Direct T2V</option><option value="references">References</option><option value="first_frame">First frame</option><option value="first_last">First + last</option></select>
            <textarea className={textareaClass} value={shot.prompt} onChange={event => patchShot(shot.id, current => ({ ...current, prompt: event.target.value }))} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1">{shot.visibleCharacterIds.map(id => <Pill key={id} tone={shot.speakingCharacterIds.includes(id) ? 'violet' : 'neutral'}>{characters[id] || id}{shot.speakingCharacterIds.includes(id) ? ' · speaking' : ' · visible'}</Pill>)}</div>
          <div className="mt-1 flex flex-wrap gap-1">{Object.entries(shot.wardrobeByCharacterId).map(([characterId, variantId]) => <Pill key={`${characterId}-${variantId}`} tone="blue">{characters[characterId] || characterId} · wardrobe {variantId}</Pill>)}</div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-border p-2">
              <div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-semibold uppercase text-text-muted">Exact routed manifest</span>{manifest && <Pill tone={manifest.errors.length ? 'red' : manifest.warnings.length ? 'amber' : 'green'}>{manifest.strategy}</Pill>}</div>
              {manifest ? <><div className="flex flex-wrap gap-1">{manifest.selected.map(reference => <Pill key={`${reference.assetId}-${reference.referenceRole}`} tone={reference.priority <= 3 ? 'violet' : 'blue'}>{reference.referenceRole.replaceAll('_', ' ')} · {reference.assetId}</Pill>)}</div>{manifest.omitted.map(reference => <p key={`${reference.assetId}-${reference.reason}`} className="mt-1 text-[10px] text-text-muted">Omitted {reference.assetId}: {reference.reason}</p>)}{manifest.warnings.map(warning => <p key={warning} className="mt-1 text-[10px] text-amber-300">{warning}</p>)}{manifest.errors.map(problem => <p key={problem} className="mt-1 text-[10px] text-red-300">{problem}</p>)}</> : <p className="text-[10px] text-text-muted">Route references to preview the exact H3 input.</p>}
            </div>
            <div className="rounded-lg border border-border p-2">
              <span className="text-[10px] font-semibold uppercase text-text-muted">Manual reference policy</span>
              <div className="mt-2 grid max-h-40 gap-1 overflow-y-auto">{Object.values(series.assets).filter(asset => ['image', 'character', 'location', 'prop'].includes(asset.kind)).map(asset => <div key={asset.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 text-[10px] text-text-secondary"><span className="truncate" title={asset.id}>{asset.id}</span><label className="flex items-center gap-1"><input type="checkbox" checked={shot.referencePolicy.manualIncludeAssetIds.includes(asset.id)} onChange={event => patchShot(shot.id, current => ({ ...current, referencePolicy: { ...current.referencePolicy, mode: 'manual', manualIncludeAssetIds: event.target.checked ? [...current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id), asset.id] : current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id), manualExcludeAssetIds: event.target.checked ? current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id) : current.referencePolicy.manualExcludeAssetIds }, referenceManifest: undefined }))} />include</label><label className="flex items-center gap-1"><input type="checkbox" checked={shot.referencePolicy.manualExcludeAssetIds.includes(asset.id)} onChange={event => patchShot(shot.id, current => ({ ...current, referencePolicy: { ...current.referencePolicy, mode: 'manual', manualExcludeAssetIds: event.target.checked ? [...current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id), asset.id] : current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id), manualIncludeAssetIds: event.target.checked ? current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id) : current.referencePolicy.manualIncludeAssetIds }, referenceManifest: undefined }))} />exclude</label></div>)}</div>
              <div className="mt-2 flex flex-wrap gap-2"><label className={secondaryButton}><Upload size={12} />Composed start<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadComposedFrame(shot, file, 'composed_start_frame') }} /></label><label className={secondaryButton}><Upload size={12} />Composed end<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadComposedFrame(shot, file, 'composed_end_frame') }} /></label></div>
            </div>
          </div>
          {shot.attempts.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{shot.attempts.map(attempt => <Pill key={attempt.id} tone={attempt.status === 'completed' ? 'green' : attempt.status === 'failed' ? 'red' : attempt.status === 'running' ? 'violet' : 'neutral'}>{attempt.status} · seed {attempt.seed ?? 'random'} · {(attempt.elapsedMs / 1000).toFixed(1)}s · {attempt.model}</Pill>)}</div>}
        </article>
      })}</div>
    </SectionCard>
  </div>
}
