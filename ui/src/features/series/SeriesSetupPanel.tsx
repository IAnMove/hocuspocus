import { useEffect, useRef, useState } from 'react'
import { Check, CheckCircle2, ImagePlus, Loader2, Sparkles, Square } from 'lucide-react'
import * as api from '../../api/client'
import { generateImageAsset } from '../../lib/imageGeneration'
import { useStore } from '../../stores/useStore'
import { SeriesField, SectionCard } from './components'
import { greenButton, inputClass, primaryButton, secondaryButton, selectClass, textareaClass } from './styles'
import type { SeriesJobStatus, SeriesProject } from './types'

export function SeriesSetupPanel({
  workspace, series, update, saveNow, replaceSeries, job, setJob,
}: {
  workspace: string
  series: SeriesProject
  update: (updater: (series: SeriesProject) => SeriesProject) => void
  saveNow: () => Promise<unknown>
  replaceSeries: (series: SeriesProject) => void
  job: SeriesJobStatus | null
  setJob: (job: SeriesJobStatus | null) => void
}) {
  const productionProfile = useStore(state => state.productionProfile)
  const [instruction, setInstruction] = useState('')
  const [knownSeriesRequest, setKnownSeriesRequest] = useState('')
  const [imageMode, setImageMode] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState<string | null>(null)
  const adoptedKnownSeriesJob = useRef('')
  const patch = (value: Partial<SeriesProject>) => update(current => ({ ...current, ...value }))
  const patchProvider = (value: Partial<SeriesProject['provider']>) => update(current => ({
    ...current, provider: { ...current.provider, ...value },
  }))
  const patchVideo = (value: Partial<SeriesProject['provider']['videoSettings']>) => update(current => ({
    ...current,
    provider: {
      ...current.provider,
      videoSettings: { ...current.provider.videoSettings, ...value },
    },
  }))
  const complete = Boolean(series.title.trim() && series.premise.trim() && series.visualStyle.trim())
  const useGlobalProfile = () => patchProvider({
    useGlobalProfile: true,
    writingProvider: productionProfile.text.provider === 'minimax' ? 'minimax' : 'maestro',
    writingModel: productionProfile.text.model,
    writingBaseUrl: productionProfile.text.provider === 'minimax' ? 'https://api.minimax.io/v1' : '',
    imageProvider: productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
    imageModel: productionProfile.image.model,
    videoModel: productionProfile.video.model,
    videoSettings: {
      ...series.provider.videoSettings,
      resolution: productionProfile.video.settings.resolution,
      orientation: productionProfile.video.settings.aspectRatio === '9:16' || productionProfile.video.settings.aspectRatio === '3:4'
        ? 'portrait' : 'landscape',
      numInferenceSteps: productionProfile.video.settings.steps,
      flowShift: productionProfile.video.settings.flowShift,
      audioShift: productionProfile.video.settings.audioShift,
      modelProfile: productionProfile.video.settings.profile,
    },
  })
  useEffect(() => {
    if (job?.jobType === 'canon') setImageMode(job.generateImages === true)
    if (!job || job.jobType !== 'canon' || !['queued', 'running', 'cancelling'].includes(job.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.fetchSeriesPlanJob(job.jobId).then(value => { if (active) setJob(value) })
        .catch(reason => { if (active) setError((reason as Error).message) })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [job, setJob])
  useEffect(() => {
    if (
      !job?.bootstrapKnownSeries || job.status !== 'completed' || !job.autoApplied ||
      adoptedKnownSeriesJob.current === job.jobId
    ) return
    adoptedKnownSeriesJob.current = job.jobId
    void api.fetchSeriesProject(workspace, series.id).then(replaceSeries).catch(reason => {
      adoptedKnownSeriesJob.current = ''
      setError((reason as Error).message)
    })
  }, [job, replaceSeries, series.id, workspace])
  const startKnownSeries = async () => {
    const request = knownSeriesRequest.trim()
    if (request.length < 3) return
    const hasAuthoredContent = Boolean(
      series.characters.length || series.locations.length || series.props.length ||
      series.premise.trim() || series.visualStyle.trim() ||
      (series.title.trim() && series.title.trim().toLowerCase() !== 'untitled series'),
    )
    if (hasAuthoredContent && !window.confirm(
      'This will replace the current setup and bible with a generated draft. Existing episodes and uploaded assets are preserved. Continue?',
    )) return
    setBusy(true); setError(null); setImageMode(false)
    try {
      await saveNow()
      setJob(await api.startSeriesCanonPreparation(workspace, series.id, {
        instruction: request,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
        generateImages: false,
        bootstrapKnownSeries: true,
        autoApply: true,
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const startCanon = async (withImages: boolean) => {
    setBusy(true); setError(null); setImageMode(withImages)
    try {
      await saveNow()
      setJob(await api.startSeriesCanonPreparation(workspace, series.id, {
        instruction,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
        generateImages: withImages,
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const generateCanonImages = async (applied: SeriesProject) => {
    let current = applied
    const targets = [
      ...applied.characters.filter(item => !item.referenceAssetIds.length).map(item => ({
        ownerType: 'character' as const, ownerId: item.id, name: item.name,
        prompt: [applied.visualStyle, applied.characterVisualStyle, item.identityLock, item.appearance, 'One character identity portrait, clear face, no text, no contact sheet.'].filter(Boolean).join(' '),
        referenceRole: 'primary_portrait', kind: 'character' as const,
      })),
      ...applied.locations.filter(item => !item.referenceAssetIds.length).map(item => ({
        ownerType: 'location' as const, ownerId: item.id, name: item.name,
        prompt: [applied.visualStyle, item.description, 'One canonical establishing image, no people unless explicitly required, no text, no contact sheet.'].filter(Boolean).join(' '),
        referenceRole: 'location_reference', kind: 'location' as const,
      })),
    ]
    for (let index = 0; index < targets.length; index += 1) {
      const target = targets[index]
      setProgress(`Generating canon image ${index + 1}/${targets.length}: ${target.name}`)
      const generated = await generateImageAsset(
        applied.provider.imageProvider === 'minimax' ? 'minimax' : 'maestro',
        target.prompt, applied.provider.imageModel, undefined, '',
        { panelId: `series-${applied.id}-${target.ownerId}`, aspectRatio: '1:1' },
      )
      const response = await fetch(generated.source)
      if (!response.ok) throw new Error(`Generated image for ${target.name} is no longer available`)
      const blob = await response.blob()
      const upload = await api.uploadImage(new File(
        [blob], generated.name || `${target.ownerId}.png`, { type: blob.type || 'image/png' },
      ))
      const imported = await api.importSeriesAsset(workspace, applied.id, {
        uploadPath: upload.path, name: generated.name || target.name,
        ownerType: target.ownerType, ownerId: target.ownerId, kind: target.kind,
        referenceRole: target.referenceRole,
        metadata: {
          prompt: target.prompt, model: generated.model,
          provider: applied.provider.imageProvider, createdAt: generated.createdAt,
        },
      })
      current = imported.series
      replaceSeries(current)
    }
    return current
  }
  const applyCanon = async () => {
    if (!job) return
    setBusy(true); setError(null); setProgress('Applying reviewed canon proposal…')
    try {
      const applied = await api.applySeriesCanonPlanJob(job.jobId)
      replaceSeries(applied)
      if (imageMode) await generateCanonImages(applied)
      setProgress('')
      setJob(null)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <div className="space-y-4 pb-10">
      <div className={`rounded-xl border px-4 py-3 ${complete ? 'border-green-500/30 bg-green-500/10' : 'border-violet-500/30 bg-violet-500/10'}`}>
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <CheckCircle2 size={15} className={complete ? 'text-green-400' : 'text-violet-400'} />
          {complete ? 'Core setup ready' : 'Complete the violet fields before planning canon or episodes'}
        </div>
      </div>
      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

      <SectionCard title="Fill from a known series · one click" description="Describe the existing series or universe. The writing model fills setup, recurring cast, relationships, locations, props, rules and chronology as an editable draft.">
        <textarea
          className={textareaClass}
          value={knownSeriesRequest}
          onChange={event => setKnownSeriesRequest(event.target.value)}
          placeholder="Quiero nuevos capítulos de Seinfeld, respetando sus personajes, relaciones, lugares y tono…"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className={greenButton}
            disabled={knownSeriesRequest.trim().length < 3 || busy || Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))}
            onClick={() => void startKnownSeries()}
          ><Sparkles size={13} />Build known-series bible</button>
          {job?.bootstrapKnownSeries && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(setJob)}><Square size={13} />Cancel after current LLM call</button>}
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-amber-200">Uses the selected writing model's general knowledge, not live web research. It does not copy scripts or dialogue, and facts may be incomplete: review the draft before approving canon. Publishing or monetizing third-party characters still requires the appropriate rights.</p>
        {job?.bootstrapKnownSeries && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3">
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            {['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}
            <span>{job.status} · {job.message}</span><span className="ml-auto">{job.current}/{job.total}</span>
          </div>
          {job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}
          {job.applyError && <p className="mt-2 text-[10px] text-amber-300">{job.applyError} Start the action again after reviewing your edits.</p>}
          {job.status === 'completed' && job.autoApplied && job.seriesResult && <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/5 p-3">
            <p className="text-[11px] text-green-200">Draft filled: {job.seriesResult.characters.length} recurring characters · {job.seriesResult.locations.length} locations · {job.seriesResult.relationships.length} relationships · {job.seriesResult.props?.length || 0} props.</p>
            <p className="mt-1 text-[10px] text-text-muted">Review Series identity, Source mode and the Canon tabs. Nothing has been approved automatically.</p>
            <details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">Inspect generated data</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify(job.seriesResult, null, 2)}</pre></details>
          </div>}
          {(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(setJob)}>Resume known-series fill</button>}
        </div>}
      </SectionCard>

      <SectionCard title="Prepare the series bible" description="Both actions create a durable proposal first. Nothing replaces hand-edited canon until you inspect and apply the diff.">
        <textarea className={textareaClass} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="Optional canon direction or constraints…" />
        <div className="mt-3 flex flex-wrap gap-2"><button className={primaryButton} disabled={!complete || busy || Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))} onClick={() => void startCanon(false)}><Sparkles size={13} />Prepare canon text</button><button className={greenButton} disabled={!complete || busy || (series.provider.imageProvider === 'maestro' && !series.provider.imageModel) || Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))} onClick={() => void startCanon(true)}><ImagePlus size={13} />Prepare canon + up to 4 images</button>{job && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(setJob)}><Square size={13} />Cancel after current LLM call</button>}</div>
        {series.provider.imageProvider === 'maestro' && !series.provider.imageModel && <p className="mt-2 text-[10px] text-amber-300">Choose an explicit local image model below before using the image action; Series Lab will not silently select or download a recommended model.</p>}
        {progress && <p className="mt-2 flex items-center gap-2 text-[11px] text-violet-200"><Loader2 size={12} className="animate-spin" />{progress}</p>}
        {job && !job.bootstrapKnownSeries && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3"><div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<span>{job.status} · {job.message}</span><span className="ml-auto">{job.current}/{job.total}</span></div>{job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}{job.status === 'completed' && job.seriesResult && <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/5 p-3"><p className="text-[11px] text-green-200">Proposal: {job.seriesResult.characters.length} principal characters · {job.seriesResult.locations.length} locations · {job.seriesResult.canon.immutableRules.length} immutable rules</p><details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">Inspect exact canon proposal</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify(job.seriesResult, null, 2)}</pre></details><button className={`mt-3 ${greenButton}`} disabled={busy} onClick={() => void applyCanon()}><Check size={13} />Apply reviewed canon{imageMode ? ' and generate missing images' : ''}</button></div>}{(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(setJob)}>Resume canon preparation</button>}</div>}
      </SectionCard>

      <SectionCard title="Series identity" description="These fields are reused in every episode snapshot.">
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label="Title" required><input className={inputClass} value={series.title} onChange={event => patch({ title: event.target.value })} /></SeriesField>
          <SeriesField label="Format"><select className={selectClass} value={series.format} onChange={event => patch({ format: event.target.value as SeriesProject['format'] })}>
            <option value="episodic">Episodic</option><option value="serial">Serial</option><option value="hybrid">Hybrid</option>
          </select></SeriesField>
          <SeriesField label="Premise" required><textarea className={textareaClass} value={series.premise} onChange={event => patch({ premise: event.target.value })} /></SeriesField>
          <SeriesField label="Logline"><textarea className={textareaClass} value={series.logline} onChange={event => patch({ logline: event.target.value })} /></SeriesField>
          <SeriesField label="Language"><input className={inputClass} value={series.language} onChange={event => patch({ language: event.target.value })} /></SeriesField>
          <SeriesField label="Spoken video language" hint="Forces every dialogue prompt; regional accent remains model-dependent."><select className={selectClass} value={series.spokenLanguage} onChange={event => patch({ spokenLanguage: event.target.value })}><option value="">Auto from dialogue</option><option value="Español de España">Español de España</option><option value="Español latinoamericano">Español latinoamericano</option><option value="English">English</option><option value="French">Français</option><option value="Italian">Italiano</option></select></SeriesField>
          <SeriesField label="Default episode duration" hint="Long episodes add more shots. Dialogue shots are timed from syllables and rounded upward to the model's native duration."><input className={inputClass} type="number" min={15} max={3600} value={series.defaultEpisodeDurationSeconds} onChange={event => patch({ defaultEpisodeDurationSeconds: Number(event.target.value) })} /></SeriesField>
          <SeriesField label="Genre"><input className={inputClass} value={series.genre} onChange={event => patch({ genre: event.target.value })} /></SeriesField>
          <SeriesField label="Tone"><input className={inputClass} value={series.tone} onChange={event => patch({ tone: event.target.value })} /></SeriesField>
          <SeriesField label="Audience"><input className={inputClass} value={series.audience} onChange={event => patch({ audience: event.target.value })} /></SeriesField>
        </div>
      </SectionCard>

      <SectionCard title="Visual continuity" description="Style is separate from narrative prompts and is frozen into each episode snapshot.">
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label="Visual style" required><textarea className={textareaClass} value={series.visualStyle} onChange={event => patch({ visualStyle: event.target.value })} /></SeriesField>
          <SeriesField label="Character visual style"><textarea className={textareaClass} value={series.characterVisualStyle} onChange={event => patch({ characterVisualStyle: event.target.value })} /></SeriesField>
          <SeriesField label="Camera language"><textarea className={textareaClass} value={series.cameraLanguage} onChange={event => patch({ cameraLanguage: event.target.value })} /></SeriesField>
          <SeriesField label="Readable text policy" hint="Dialogue remains audio; disabling this also adds a no-captions constraint to H3 prompts.">
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.allowClipText} onChange={event => patch({ allowClipText: event.target.checked })} />Allow intentional readable text in clips</label>
          </SeriesField>
          <SeriesField label="Native dialogue" hint="MiniMax H3 native audio uses exact dialogue and emotion, but mouth synchronization remains best-effort.">
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.bestEffortLipSyncAcknowledged} onChange={event => patch({ bestEffortLipSyncAcknowledged: event.target.checked })} />I understand lip sync is best-effort</label>
          </SeriesField>
          <SeriesField label="Fixed protagonist" hint="Optional. Requires an approved primary portrait and routes it as the identity authority.">
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.protagonistConsistency} onChange={event => patch({ protagonistConsistency: event.target.checked, protagonistCharacterId: event.target.checked ? (series.protagonistCharacterId || series.characters[0]?.id || '') : series.protagonistCharacterId })} />Create/approve protagonist first</label>
            {series.protagonistConsistency && <select className={`${selectClass} mt-2`} value={series.protagonistCharacterId} onChange={event => patch({ protagonistCharacterId: event.target.value })}><option value="">Choose protagonist</option>{series.characters.map(character => <option key={character.id} value={character.id}>{character.name || 'Unnamed character'}</option>)}</select>}
            {series.protagonistConsistency && (() => { const character = series.characters.find(item => item.id === series.protagonistCharacterId); const ready = Boolean(character?.primaryReferenceAssetId && series.assets[character.primaryReferenceAssetId] && character.approval === 'approved'); return <p className={`mt-1 text-[10px] ${ready ? 'text-emerald-200' : 'text-amber-300'}`}>{ready ? 'Approved primary identity ready.' : 'Generate or upload this character portrait in Canon, mark it primary, then approve it before rendering.'}</p> })()}
          </SeriesField>
        </div>
      </SectionCard>

      <SectionCard title="Source mode and rights note" description="Known-universe behavior is experimental; its generated master prompt remains fully editable.">
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label="Source mode"><select className={selectClass} value={series.sourceMode} onChange={event => patch({ sourceMode: event.target.value as SeriesProject['sourceMode'] })}>
            <option value="original">Original</option><option value="known_universe_experimental">Known universe · experimental</option><option value="hybrid">Hybrid</option>
          </select></SeriesField>
          <SeriesField label="Rights/source note" hint="Publication or monetization of third-party characters requires appropriate rights."><textarea className={textareaClass} value={series.rightsNote} onChange={event => patch({ rightsNote: event.target.value })} /></SeriesField>
          {series.sourceMode !== 'original' && <div className="lg:col-span-2"><SeriesField label="Master universe prompt" required><textarea className={textareaClass} value={series.masterUniversePrompt} onChange={event => patch({ masterUniversePrompt: event.target.value })} /></SeriesField></div>}
          {series.sourceMode !== 'original' && <p className="lg:col-span-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-[10px] leading-relaxed text-amber-200">Experimental direct mode relies on probabilistic model familiarity and can drift across model versions. Review the generated master prompt and canon, then add approved visual references when identity matters.</p>}
        </div>
      </SectionCard>

      <SectionCard title="Providers and render canvas" description="Series keeps its own saved defaults; a job records the exact effective values.">
        <div className="mb-3 grid max-w-xl grid-cols-2 gap-2">
          <button type="button" className={`${secondaryButton} ${series.provider.useGlobalProfile ? 'border-violet-400 text-violet-200' : ''}`} onClick={useGlobalProfile}>Use global profile</button>
          <button type="button" className={`${secondaryButton} ${!series.provider.useGlobalProfile ? 'border-violet-400 text-violet-200' : ''}`} onClick={() => patchProvider({ useGlobalProfile: false })}>Override in this project</button>
        </div>
        {series.provider.useGlobalProfile && <p className="mb-3 text-[10px] text-green-300">Global: {productionProfile.text.model} · {productionProfile.image.model} · {productionProfile.video.model}</p>}
        <fieldset disabled={series.provider.useGlobalProfile} className="disabled:opacity-50">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <SeriesField label="Writing provider"><select className={selectClass} value={series.provider.writingProvider} onChange={event => patchProvider({ writingProvider: event.target.value as SeriesProject['provider']['writingProvider'] })}>
            <option value="maestro">HocusPocus local</option><option value="deepseek">DeepSeek</option><option value="minimax">MiniMax</option><option value="openai">OpenAI</option><option value="openai-compatible">Compatible</option>
          </select></SeriesField>
          <SeriesField label="Writing model"><input className={inputClass} value={series.provider.writingModel} onChange={event => patchProvider({ writingModel: event.target.value })} placeholder="Saved provider default" /></SeriesField>
          <SeriesField label="Image provider"><select className={selectClass} value={series.provider.imageProvider} onChange={event => patchProvider({ imageProvider: event.target.value })}><option value="maestro">HocusPocus local · explicit model</option><option value="minimax">MiniMax Image API</option></select></SeriesField>
          <SeriesField label="Image model"><input className={inputClass} value={series.provider.imageModel} disabled={series.provider.imageProvider === 'minimax'} onChange={event => patchProvider({ imageModel: event.target.value })} placeholder={series.provider.imageProvider === 'minimax' ? 'MiniMax image-01' : 'Exact saved local model ID'} /></SeriesField>
          <SeriesField label="Video model"><select className={selectClass} value={series.provider.videoModel} onChange={event => patchProvider({ videoModel: event.target.value })}>
            <option value="minimax_h3_legacy">H3 Legacy Quality · ConvRot</option><option value="minimax_h3">MiniMax H3 · pruned</option><option value="minimax_h3_full">MiniMax H3 · full</option>
          </select></SeriesField>
          <SeriesField label="Resolution"><select className={selectClass} value={String(series.provider.videoSettings.resolution || '480p')} onChange={event => patchVideo({ resolution: event.target.value })}>
            <option value="480p">480p · nearest native</option><option value="540p">540p · 960×544 / 544×960</option><option value="720p">720p · nearest native</option><option value="768p">768p · 1344×768 / 768×1344</option>
          </select></SeriesField>
          <SeriesField label="Orientation"><select className={selectClass} value={String(series.provider.videoSettings.orientation || 'landscape')} onChange={event => patchVideo({ orientation: event.target.value as 'landscape' | 'portrait' })}>
            <option value="landscape">Landscape · 16:9</option><option value="portrait">Portrait · 9:16 Shorts</option>
          </select></SeriesField>
          <SeriesField label="H3 inference steps"><input className={inputClass} type="number" min={1} max={50} value={Number(series.provider.videoSettings.numInferenceSteps || 20)} onChange={event => patchVideo({ numInferenceSteps: Number(event.target.value) })} /></SeriesField>
        </div>
        </fieldset>
      </SectionCard>
    </div>
  )
}
