import { useEffect, useMemo, useState } from 'react'
import { CheckSquare, Info, RefreshCw, Square, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { Pill, SectionCard, seriesStatusLabel } from './components'
import { SeriesShotDurationControl } from './SeriesShotDurationControl'
import { primaryButton, secondaryButton, selectClass, textareaClass } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { useUiTranslation } from '../../i18n'

export function SeriesShotsPanel({
  workspace, series, episode, updateEpisode, replaceSeries, saveNow, onAcknowledgeLipSync, onRender,
}: {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  updateEpisode: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  replaceSeries: (series: SeriesProject) => void
  saveNow: () => Promise<unknown>
  onAcknowledgeLipSync: () => Promise<void>
  onRender: (mode: 'selected' | 'missing' | 'failed' | 'all', shotIds?: string[]) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [routing, setRouting] = useState(false)
  const [acknowledgingLipSync, setAcknowledgingLipSync] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const characters = useMemo(() => Object.fromEntries(series.characters.map(item => [item.id, item.name])), [series.characters])
  const locations = useMemo(() => Object.fromEntries(series.locations.map(item => [item.id, item.name])), [series.locations])
  const selectableShotIds = useMemo(
    () => episode.shots.filter(shot => !shot.approvedAttemptId).map(shot => shot.id),
    [episode.shots],
  )
  const selectedCount = selectableShotIds.filter(id => selected.has(id)).length
  const allSelected = selectableShotIds.length > 0 && selectedCount === selectableShotIds.length
  const hasDialogueShots = episode.shots.some(shot => shot.dialogueBeats.length > 0)
  useEffect(() => {
    const selectableIds = new Set(selectableShotIds)
    setSelected(current => {
      const next = new Set([...current].filter(id => selectableIds.has(id)))
      return next.size === current.size && [...next].every(id => current.has(id)) ? current : next
    })
  }, [episode.id, selectableShotIds])
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
  const acknowledgeLipSync = async () => {
    setAcknowledgingLipSync(true); setError(null)
    try { await onAcknowledgeLipSync() }
    catch (reason) { setError((reason as Error).message) }
    finally { setAcknowledgingLipSync(false) }
  }
  return <div className="space-y-4 pb-10">
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
    <SectionCard title={t('shots.title')} description={t('shots.description', { count: episode.shots.length, duration: totalDuration.toFixed(1) })} action={<button className={secondaryButton} disabled={routing || !episode.shots.length} onClick={() => void routeAll()}><RefreshCw size={13} className={routing ? 'animate-spin' : ''} />{t('shots.routeAll')}</button>}>
      {hasDialogueShots && !series.bestEffortLipSyncAcknowledged && <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
        <Info size={16} className="shrink-0 text-amber-300" />
        <div className="min-w-0 flex-1"><p className="font-semibold">{t('shots.lipSyncTitle')}</p><p className="mt-0.5 text-[10px] text-amber-200/80">{t('shots.lipSyncBody')}</p></div>
        <button className={secondaryButton} disabled={acknowledgingLipSync} onClick={() => void acknowledgeLipSync()}>{acknowledgingLipSync ? <RefreshCw size={13} className="animate-spin" /> : <CheckSquare size={13} />}{t('shots.lipSyncEnable')}</button>
      </div>}
      <div className="mb-3 flex flex-wrap gap-2">
        <button type="button" className={secondaryButton} aria-pressed={allSelected} disabled={!selectableShotIds.length} onClick={() => setSelected(allSelected ? new Set() : new Set(selectableShotIds))}>{allSelected ? <CheckSquare size={13} /> : <Square size={13} />}{allSelected ? t('shots.clearSelection') : t('shots.selectAll', { count: selectableShotIds.length })}</button>
        <button className={primaryButton} disabled={!selectedCount || (hasDialogueShots && !series.bestEffortLipSyncAcknowledged)} onClick={() => onRender('selected', selectableShotIds.filter(id => selected.has(id)))}><CheckSquare size={13} />{t('shots.renderSelected', { count: selectedCount })}</button>
        <button className={secondaryButton} disabled={hasDialogueShots && !series.bestEffortLipSyncAcknowledged} onClick={() => onRender('missing')}>{t('shots.renderMissing')}</button><button className={secondaryButton} disabled={hasDialogueShots && !series.bestEffortLipSyncAcknowledged} onClick={() => onRender('failed')}>{t('shots.retryFailed')}</button><button className={secondaryButton} disabled={hasDialogueShots && !series.bestEffortLipSyncAcknowledged} onClick={() => onRender('all')}>{t('shots.renderUnapproved')}</button>
      </div>
      {!episode.shots.length && <p className="rounded-lg border border-violet-500/30 bg-violet-500/10 p-4 text-xs text-violet-200">{t('shots.empty')}</p>}
      <div className="space-y-3">{episode.shots.map(shot => {
        const manifest = shot.referenceManifest
        const approved = shot.attempts.find(item => item.id === shot.approvedAttemptId)
        const selectable = !shot.approvedAttemptId
        const isSelected = selectable && selected.has(shot.id)
        return <article key={shot.id} id={`series-shot-${shot.id}`} className="rounded-xl border border-border bg-bg-primary p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded border border-dashed border-border bg-bg-tertiary text-[8px] uppercase text-text-muted">{t('shots.shotOrder', { order: shot.order })}<br />{t('shots.poster')}</div>
            <button
              type="button"
              disabled={!selectable}
              aria-pressed={isSelected}
              aria-label={selectable ? (isSelected ? t('shots.deselectAria', { order: shot.order }) : t('shots.selectAria', { order: shot.order })) : t('shots.approvedAria', { order: shot.order })}
              className="disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => setSelected(current => {
                if (!selectable) return current
                const next = new Set(current)
                if (next.has(shot.id)) next.delete(shot.id); else next.add(shot.id)
                return next
              })}
            >{isSelected ? <CheckSquare size={16} className="text-violet-400" aria-hidden="true" /> : <Square size={16} className="text-text-muted" aria-hidden="true" />}</button>
            <Pill tone="blue">#{shot.order}</Pill><strong className="text-xs text-text-primary">{shot.framing || t('shots.shotFallback')}</strong><Pill>{shot.durationSeconds}s</Pill>
            {shot.primarySpeakerId && <Pill tone="violet">{t('shots.speaker', { name: characters[shot.primarySpeakerId] || shot.primarySpeakerId })}</Pill>}
            {shot.locationId && <Pill>{locations[shot.locationId] || shot.locationId}</Pill>}
            {approved && <Pill tone="green">{t('shots.approvedModel', { model: approved.model })}</Pill>}
            <button className={`ml-auto ${secondaryButton}`} disabled={routing} onClick={() => void routeOne(shot.id)}><RefreshCw size={12} />{t('shots.reroute')}</button>
          </div>
          <div className="mt-3 grid gap-2 lg:grid-cols-[120px_120px_1fr]">
            <SeriesShotDurationControl workspace={workspace} series={series} shot={shot} onChange={planned => patchShot(shot.id, () => planned)} />
            <select aria-label={t('shots.strategyAria', { order: shot.order })} className={selectClass} value={shot.renderStrategy} onChange={event => patchShot(shot.id, current => ({ ...current, renderStrategy: event.target.value as SeriesShot['renderStrategy'], referenceManifest: undefined }))}><option value="auto">{t('shots.auto')}</option><option value="direct">{t('shots.direct')}</option><option value="references">{t('shots.references')}</option><option value="first_frame">{t('shots.firstFrame')}</option><option value="first_last">{t('shots.firstLast')}</option></select>
            <textarea aria-label={t('shots.promptAria', { order: shot.order })} className={textareaClass} value={shot.prompt} onChange={event => patchShot(shot.id, current => ({ ...current, prompt: event.target.value }))} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1">{shot.visibleCharacterIds.map(id => <Pill key={id} tone={shot.speakingCharacterIds.includes(id) ? 'violet' : 'neutral'}>{characters[id] || id}{shot.speakingCharacterIds.includes(id) ? t('shots.speaking') : t('shots.visible')}</Pill>)}</div>
          <div className="mt-1 flex flex-wrap gap-1">{Object.entries(shot.wardrobeByCharacterId).map(([characterId, variantId]) => <Pill key={`${characterId}-${variantId}`} tone="blue">{t('shots.wardrobe', { name: characters[characterId] || characterId, variant: variantId })}</Pill>)}</div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-border p-2">
              <div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-semibold uppercase text-text-muted">{t('shots.manifestTitle')}</span>{manifest && <Pill tone={manifest.errors.length ? 'red' : manifest.warnings.length ? 'amber' : 'green'}>{manifest.strategy}</Pill>}</div>
              {manifest ? <><div className="flex flex-wrap gap-1">{manifest.selected.map(reference => <Pill key={`${reference.assetId}-${reference.referenceRole}`} tone={reference.priority <= 3 ? 'violet' : 'blue'}>{reference.referenceRole.replaceAll('_', ' ')} · {reference.assetId}</Pill>)}</div>{manifest.omitted.map(reference => <p key={`${reference.assetId}-${reference.reason}`} className="mt-1 text-[10px] text-text-muted">{t('shots.omitted', { id: reference.assetId, reason: reference.reason })}</p>)}{manifest.warnings.map(warning => <p key={warning} className="mt-1 text-[10px] text-amber-300">{warning}</p>)}{manifest.errors.map(problem => <p key={problem} className="mt-1 text-[10px] text-red-300">{problem}</p>)}</> : <p className="text-[10px] text-text-muted">{t('shots.routePreview')}</p>}
            </div>
            <div className="rounded-lg border border-border p-2">
              <span className="text-[10px] font-semibold uppercase text-text-muted">{t('shots.policyTitle')}</span>
              <div className="mt-2 grid max-h-40 gap-1 overflow-y-auto">{Object.values(series.assets).filter(asset => ['image', 'character', 'location', 'prop'].includes(asset.kind)).map(asset => <div key={asset.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 text-[10px] text-text-secondary"><span className="truncate" title={asset.id}>{asset.id}</span><label className="flex items-center gap-1"><input type="checkbox" aria-label={t('shots.includeAria', { id: asset.id, order: shot.order })} checked={shot.referencePolicy.manualIncludeAssetIds.includes(asset.id)} onChange={event => patchShot(shot.id, current => ({ ...current, referencePolicy: { ...current.referencePolicy, mode: 'manual', manualIncludeAssetIds: event.target.checked ? [...current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id), asset.id] : current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id), manualExcludeAssetIds: event.target.checked ? current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id) : current.referencePolicy.manualExcludeAssetIds }, referenceManifest: undefined }))} />{t('shots.include')}</label><label className="flex items-center gap-1"><input type="checkbox" aria-label={t('shots.excludeAria', { id: asset.id, order: shot.order })} checked={shot.referencePolicy.manualExcludeAssetIds.includes(asset.id)} onChange={event => patchShot(shot.id, current => ({ ...current, referencePolicy: { ...current.referencePolicy, mode: 'manual', manualExcludeAssetIds: event.target.checked ? [...current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id), asset.id] : current.referencePolicy.manualExcludeAssetIds.filter(id => id !== asset.id), manualIncludeAssetIds: event.target.checked ? current.referencePolicy.manualIncludeAssetIds.filter(id => id !== asset.id) : current.referencePolicy.manualIncludeAssetIds }, referenceManifest: undefined }))} />{t('shots.exclude')}</label></div>)}</div>
              <div className="mt-2 flex flex-wrap gap-2"><label className={secondaryButton}><Upload size={12} />{t('shots.composedStart')}<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadComposedFrame(shot, file, 'composed_start_frame') }} /></label><label className={secondaryButton}><Upload size={12} />{t('shots.composedEnd')}<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadComposedFrame(shot, file, 'composed_end_frame') }} /></label></div>
            </div>
          </div>
          {shot.attempts.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{shot.attempts.map(attempt => <Pill key={attempt.id} tone={attempt.status === 'completed' ? 'green' : attempt.status === 'failed' ? 'red' : attempt.status === 'running' ? 'violet' : 'neutral'}>{t('shots.attempt', { status: seriesStatusLabel(t, attempt.status), seed: attempt.seed ?? t('shots.seedRandom'), elapsed: (attempt.elapsedMs / 1000).toFixed(1), model: attempt.model })}</Pill>)}</div>}
        </article>
      })}</div>
    </SectionCard>
  </div>
}
