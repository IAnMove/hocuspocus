import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Cpu, Loader2, Palette, Play, RefreshCw, Square, X } from 'lucide-react'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { Hunyuan3DAdvancedSettings } from './Hunyuan3DAdvancedSettings'
import { ModelSelector } from './ModelSelector'
import { Model3DEngineInputs } from './Model3DEngineInputs'
import { model3dInputState } from '../../lib/model3dInputState'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import {
  cancelHunyuan3DJob,
  fetchOutputs,
  fetchHunyuan3DCapabilities,
  fetchHunyuan3DJob,
  startHunyuan3DJob,
  type ApiOutput,
  type Hunyuan3DCapabilities,
  type Hunyuan3DJob,
} from '../../api/client'

type ViewName = 'front' | 'left' | 'right' | 'back'
type UploadedView = { path: string; name: string; url: string; workspace?: string }
type RetextureSource = { path: string; name: string; thumbnail?: string | null }

const ACTIVE_3D_JOB_STATUSES = new Set(['queued', 'waiting', 'waiting_resource', 'running', 'cancelling'])

function asImageOutput(value?: UploadedView): ApiOutput | undefined {
  if (!value) return undefined
  return { name: value.name, type: 'image', mode: null, size: 0, created_at: 0, url: value.url, thumbnail_url: value.url }
}

function HunyuanViewField({
  view, value, required, disabled = false, items, onChoose,
}: {
  view: ViewName
  value?: UploadedView
  required?: boolean
  disabled?: boolean
  items: ApiOutput[]
  onChoose: (item: ApiOutput | null) => void
}) {
  const { t } = useUiTranslation('scene3d')
  const viewLabel = t(`views.${view}`)
  return (
    <div className="min-w-0">
      {disabled ? (
        <div aria-disabled="true" className="flex aspect-square items-center justify-center rounded-lg border border-border opacity-40"><X size={18} aria-label={t('engines.unavailable')} /></div>
      ) : (
        <AssetInput
          label={`${viewLabel}${required ? ' *' : ''}`}
          placeholder={t('hunyuan.fromApp')}
          items={items}
          value={asImageOutput(value)}
          accept="image/*"
          optional={!required}
          constraints={{ kinds: ['image'], maxCount: 1, optional: !required }}
          onChoose={onChoose}
        />
      )}
    </div>
  )
}

export function Hunyuan3DPanel() {
  const { t } = useUiTranslation('scene3d')
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const enabledModels = useStore(state => state.enabledModels)
  const toggleModelEnabled = useStore(state => state.toggleModelEnabled)
  const modelId = useStore(state => state.params.model_type)
  const prompt = useStore(state => state.params.prompt)
  const model3dProvider = useStore(state => state.productionProfile.model3d?.provider || 'local')
  const model3dModel = useStore(state => state.productionProfile.model3d?.model || '')
  const setParam = useStore(state => state.setParam)
  const selectMaestroModel = useStore(state => state.selectModel)
  const [capabilities, setCapabilities] = useState<Hunyuan3DCapabilities | null>(null)
  const [operation, setOperation] = useState<'generate' | 'retexture'>('generate')
  const [retextureSources, setRetextureSources] = useState<RetextureSource[]>([])
  const [sourceModel, setSourceModel] = useState<RetextureSource | null>(null)
  const [sourcesLoading, setSourcesLoading] = useState(false)

  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [views, setViews] = useState<Partial<Record<ViewName, UploadedView>>>({})

  const [imageSources, setImageSources] = useState<ApiOutput[]>([])
  const [preset, setPreset] = useState('balanced')
  const [textureMode, setTextureMode] = useState('v2-turbo')
  const [steps, setSteps] = useState(5)
  const [guidance, setGuidance] = useState(5)
  const [octree, setOctree] = useState(256)
  const [chunks, setChunks] = useState(12000)
  const [seed, setSeed] = useState(1234)
  const [outputFormat, setOutputFormat] = useState('glb')
  const [textureResolution, setTextureResolution] = useState(512)
  const [cpuOffload, setCpuOffload] = useState(true)
  const [flashvdm, setFlashvdm] = useState(true)
  const [removeBackground, setRemoveBackground] = useState(true)
  const [compile, setCompile] = useState(false)
  const [reduceFace, setReduceFace] = useState(false)
  const [targetFaces, setTargetFaces] = useState(40000)
  const [mcAlgo, setMcAlgo] = useState('dmc')
  const [resolution, setResolution] = useState(1024)
  const [lowVram, setLowVram] = useState(true)
  const [cameraFov, setCameraFov] = useState(0)
  const [job, setJob] = useState<Hunyuan3DJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const completedJobRef = useRef<string | null>(null)
  const imageLoadRef = useRef(0)

  useEffect(() => {
    fetchHunyuan3DCapabilities().then(setCapabilities).catch(err => {
      setCapabilityError(err instanceof Error ? err.message : t('hunyuan.capabilitiesFailed'))
    })
  }, [t])

  const selectedModel = useMemo(() => capabilities?.models.find(model => model.id === modelId), [capabilities, modelId])
  const isRunning = !!job && ACTIVE_3D_JOB_STATUSES.has(job.status)
  const { external3d, isMultiview, remote3d, installed, canRun } = model3dInputState({
    model: selectedModel, provider: model3dProvider, operation,
    runtimeInstalled: capabilities?.runtime.installed,
    hasSource: !!sourceModel, hasFront: !!views.front, hasPrompt: !!prompt.trim(), textureMode,
  })

  const loadRetextureSources = useCallback(async () => {
    setSourcesLoading(true)
    try {
      const { outputs: files } = await fetchOutputs(0, 0, { search: '.glb', workspace: activeWorkspace })
      setRetextureSources(files
        .filter(file => file.type === 'model3d' && /\.glb$/i.test(file.name))
        .map(file => ({ path: file.name, name: file.name, thumbnail: file.thumbnail_url })))
    } catch {
      setRetextureSources([])
    } finally {
      setSourcesLoading(false)
    }
  }, [activeWorkspace])

  const loadImageSources = useCallback(async () => {
    const requestId = ++imageLoadRef.current
    setError(null)
    try {
      const { outputs: files } = await fetchOutputs(200, 0, {
        mediaType: 'image',
        workspace: activeWorkspace,
      })
      if (requestId === imageLoadRef.current) setImageSources(files.filter(file => file.type === 'image'))
    } catch (err) {
      if (requestId !== imageLoadRef.current) return
      setImageSources([])
      setError(err instanceof Error ? err.message : t('hunyuan.imagesFailed'))
    }
  }, [activeWorkspace, t])

  useEffect(() => {
    void loadImageSources()
  }, [loadImageSources])

  const chooseView = (view: ViewName, item: ApiOutput | null) => {
    setViews(current => {
      if (!item) {
        const next = { ...current }
        delete next[view]
        return next
      }
      return { ...current, [view]: { path: item.name, name: item.name, url: item.url, workspace: activeWorkspace } }
    })
  }

  useEffect(() => {
    setViews(current => {
      const next = { ...current }
      let changed = false
      for (const view of Object.keys(next) as ViewName[]) {
        if (next[view]?.workspace && next[view]?.workspace !== activeWorkspace) {
          delete next[view]
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [activeWorkspace])

  useEffect(() => {
    if (!external3d) return
    setOperation('generate')
    if (!selectedModel?.resolutions?.includes(resolution)) setResolution(1024)
  }, [external3d, selectedModel, resolution])

  useEffect(() => {
    if (operation === 'retexture') void loadRetextureSources()
  }, [operation, loadRetextureSources])

  useEffect(() => {
    if (operation !== 'retexture') return
    setOutputFormat('glb')
    if (textureMode === 'none') setTextureMode(selectedModel?.engine === 'v21' ? 'pbr' : 'v2-turbo')
  }, [operation, selectedModel?.engine, textureMode])

  const applyPreset = (presetId: string) => {
    const next = capabilities?.presets.find(item => item.id === presetId)
    if (!next) return
    setPreset(presetId)
    selectMaestroModel(next.model_id)
    setSteps(next.num_inference_steps)
    setGuidance(next.guidance_scale)
    setOctree(next.octree_resolution)
    setChunks(next.num_chunks)
    setTextureMode(next.texture_mode)
    setCpuOffload(next.cpu_offload)
    setFlashvdm(next.flashvdm)
  }

  useEffect(() => {
    if (!capabilities || capabilities.models.some(model => model.id === modelId)) return
    selectMaestroModel('hunyuan3d-2-turbo')
  }, [capabilities, modelId, selectMaestroModel])

  useEffect(() => {
    if (!selectedModel) return
    if (selectedModel.engine !== 'v21' && textureMode === 'pbr') setTextureMode('v2-turbo')
    if (selectedModel.engine === 'v21' && textureMode === 'v2-turbo') setTextureMode('pbr')
  }, [selectedModel, textureMode])

  // The backend only accepts PBR when exporting GLB (all material maps must
  // stay embedded), so coerce the format no matter how PBR was activated:
  // preset click, model switch, or manual texture selection.
  useEffect(() => {
    if (textureMode === 'pbr' && outputFormat !== 'glb') setOutputFormat('glb')
  }, [textureMode, outputFormat])

  const activeJobId = job?.job_id
  const activeJobStatus = job?.status
  const pollFailuresRef = useRef(0)

  useEffect(() => {
    pollFailuresRef.current = 0
  }, [activeJobId])

  useSerializedPoll({
    enabled: Boolean(activeJobId && ACTIVE_3D_JOB_STATUSES.has(activeJobStatus ?? '')),
    intervalMs: 1500,
    ownerKey: activeJobId,
    poll: () => fetchHunyuan3DJob(activeJobId!),
    onValue: next => {
      pollFailuresRef.current = 0
      setJob(next)
    },
    onError: err => {
      pollFailuresRef.current += 1
      const message = err instanceof Error ? err.message : t('hunyuan.statusFailed')
      setError(message)
      const lost = (err as Error & { status?: number }).status === 404
      if (lost || pollFailuresRef.current >= 4) {
        setJob(current => current && { ...current, status: 'failed', error: lost ? t('hunyuan.jobLost') : message })
      }
    },
  })

  useEffect(() => {
    if (job?.status === 'completed' && completedJobRef.current !== job.job_id) {
      completedJobRef.current = job.job_id
      void useStore.getState().maybeRefreshGallery({ message: t('hunyuan.modelReady') })
      if (job.operation === 'retexture') void loadRetextureSources()
    }
    if (job?.status === 'failed') setError(job.error || job.message)
  }, [job, loadRetextureSources, t])

  const run = async () => {
    setError(null)
    try {
      const images = Object.fromEntries(Object.entries(views).filter(([name, value]) => !!value && (isMultiview || name === 'front')).map(([name, value]) => [name, value!.path]))
      const nextJob = await startHunyuan3DJob(external3d ? {
        provider: 'local', model_id: modelId, operation: 'generate',
        workspace: activeWorkspace, images, seed, output_format: 'glb',
        texture_mode: 'native-pbr', resolution,
        low_vram: !!selectedModel?.supports_low_vram && lowVram,
        camera_fov: selectedModel?.supports_camera_fov ? cameraFov : 0,
      } : {
        operation,
        source_model: operation === 'retexture' ? sourceModel?.path : undefined,
        preset,
        provider: model3dProvider === 'local' ? undefined : model3dProvider,
        model_id: model3dProvider === 'local' ? modelId : (model3dModel || modelId),
        prompt: prompt.trim(),
        workspace: activeWorkspace,
        images,
        texture_mode: textureMode,
        num_inference_steps: steps,
        guidance_scale: guidance,
        octree_resolution: octree,
        num_chunks: Math.max(1000, Math.min(40000, chunks)),
        seed,
        output_format: outputFormat,
        texture_resolution: textureResolution,
        cpu_offload: cpuOffload,
        flashvdm,
        remove_background: removeBackground,
        compile,
        reduce_face: reduceFace,
        target_face_num: targetFaces,
        mc_algo: mcAlgo,
      })
      // A 3D model is enabled when the user actually starts using it. This
      // also happens to be the point where the isolated runtime fetches its
      // weights on first use.
      if (modelId && !enabledModels.has(modelId)) toggleModelEnabled(modelId)
      setJob(nextJob)
    } catch (err) {
      setError(err instanceof Error ? err.message : operation === 'retexture' ? t('hunyuan.retextureFailed') : t('hunyuan.generationFailed'))
    }
  }

  const cancel = async () => {
    if (!job) return
    try {
      setJob(await cancelHunyuan3DJob(job.job_id))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('hunyuan.cancelFailed'))
    }
  }

  if (capabilityError && !remote3d) return <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{capabilityError}</div>

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><Box size={15} className="text-accent-blue" /> {remote3d ? (model3dProvider === 'meshy' ? t('hunyuan.titleMeshy') : t('hunyuan.titleHi3d')) : external3d ? selectedModel?.label : t('hunyuan.title')}</div>
          <p className="text-[10px] text-text-muted mt-1">{remote3d ? t('hunyuan.subtitleRemote') : t('hunyuan.subtitle')}</p>
        </div>
        <div className="flex items-center gap-1 text-[9px] text-accent-green bg-accent-green/10 border border-accent-green/20 rounded-full px-2 py-1 whitespace-nowrap"><Cpu size={10} /> {t('hunyuan.vramBadge')}</div>
      </div>
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-bg-primary p-1">
        <button type="button" disabled={isRunning} onClick={() => setOperation('generate')} className={`rounded-md px-2 py-1.5 text-[10px] transition-colors disabled:opacity-50 ${operation === 'generate' ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:text-text-primary'}`}><span className="flex items-center justify-center gap-1"><Box size={11} /> {t('hunyuan.generateModel')}</span></button>
        <button type="button" disabled={isRunning || external3d} title={external3d ? t('engines.nativePbr') : undefined} onClick={() => setOperation('retexture')} className={`rounded-md px-2 py-1.5 text-[10px] transition-colors disabled:opacity-50 ${operation === 'retexture' ? 'bg-purple-500/15 text-purple-300' : 'text-text-muted hover:text-text-primary'}`}><span className="flex items-center justify-center gap-1"><Palette size={11} /> {t('hunyuan.retextureGlb')}</span></button>
      </div>

      {!remote3d && <ModelSelector />}
      {!installed && capabilities && <p role="status" className="text-xs text-amber-300">{selectedModel?.runtime?.install_hint || t('hunyuan.installHint')}</p>}
      {external3d && selectedModel && <>
        <p className="text-xs text-text-muted">✕ {t('engines.imageOnly')} {t('engines.hunyuanOnly')}</p>
        <Model3DEngineInputs model={selectedModel} resolution={resolution} onResolution={setResolution} lowVram={lowVram} onLowVram={setLowVram} fov={cameraFov} onFov={setCameraFov} />
        <label className="text-xs">{t('hunyuan.seed')}<input type="number" min={0} max={4294967295} value={seed} onChange={event => setSeed(Number(event.target.value))} className="ml-2 w-28 bg-bg-primary" /></label>
      </>}
      {!remote3d && !capabilities ? (
        <div className="flex items-center justify-center py-8 text-xs text-text-muted"><Loader2 size={15} className="animate-spin mr-2" /> {t('hunyuan.loadingModels')}</div>
      ) : (
        <>
          {operation === 'retexture' && <div className="space-y-2 rounded-lg border border-purple-400/30 bg-purple-500/[.06] p-3">
            <div className="flex items-center justify-between gap-2">
              <div><div className="text-[10px] font-medium uppercase tracking-wider text-purple-200">{t('hunyuan.sourceGlb')}</div><p className="mt-0.5 text-[9px] text-text-muted">{t('hunyuan.sourceGlbHelp')}</p></div>
              <button type="button" onClick={() => void loadRetextureSources()} title={t('hunyuan.refreshGallery')} className="rounded border border-border p-1.5 text-text-muted hover:text-text-primary"><RefreshCw size={11} className={sourcesLoading ? 'animate-spin' : ''} /></button>
            </div>
            <AssetInput
              label={t('hunyuan.sourceGlb')}
              placeholder={t('hunyuan.chooseOrImport')}
              items={retextureSources.map(file => ({
                name: file.name, type: 'model3d' as const, mode: null, size: 0, created_at: 0,
                url: file.thumbnail || '', thumbnail_url: file.thumbnail || '',
              }))}
              value={sourceModel ? {
                name: sourceModel.name, type: 'model3d', mode: null, size: 0, created_at: 0,
                url: sourceModel.thumbnail || '', thumbnail_url: sourceModel.thumbnail || '',
              } : undefined}
              accept=".glb,model/gltf-binary"
              optional
              constraints={{ kinds: ['model3d'], maxCount: 1, optional: true }}
              onChoose={item => {
                if (!item) setSourceModel(null)
                else setSourceModel({ path: item.name, name: item.name, thumbnail: item.thumbnail_url || item.url })
              }}
            />
            <p className="text-[8px] leading-relaxed text-text-muted">{t('hunyuan.retextureHelp')}</p>
          </div>}
          <div>
            <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('hunyuan.performance')}</label>
            <div className="grid grid-cols-2 gap-1.5">
              {(capabilities?.presets || []).map(item => (
                <button key={item.id} disabled={external3d} title={external3d ? t('engines.hunyuanOnly') : undefined} onClick={() => applyPreset(item.id)} className={`text-left rounded-lg border px-2.5 py-2 transition-colors ${preset === item.id ? 'border-accent-blue bg-accent-blue/10' : 'border-border bg-bg-tertiary hover:border-border-light'}`}>
                  <div className="text-[11px] font-medium text-text-primary">{item.label}</div>
                  <div className="text-[9px] text-text-muted mt-0.5 line-clamp-2">{item.description}</div>
                </button>
              ))}
            </div>
          </div>

          {!remote3d && <div>
            {selectedModel && <p className="text-[9px] text-text-muted mt-1">{selectedModel.description} {selectedModel.recommended_vram_gb != null && t('hunyuan.recommendedVram', { gb: selectedModel.recommended_vram_gb })}</p>}
          </div>}

          {!isMultiview && (
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">{operation === 'retexture' ? t('hunyuan.promptRetexture') : t('hunyuan.promptGenerate')}</label>
              <textarea disabled={external3d} title={external3d ? t('engines.imageOnly') : undefined} value={prompt} onChange={event => setParam('prompt', event.target.value)} rows={3} placeholder={operation === 'retexture' ? t('hunyuan.placeholderRetexture') : t('hunyuan.placeholderGenerate')} className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary resize-none focus:outline-none focus:border-accent-blue" />
            </div>
          )}

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] text-text-muted uppercase tracking-wider">{isMultiview ? t('hunyuan.referenceViews') : operation === 'retexture' ? t('hunyuan.textureReference') : t('hunyuan.referenceImage')}</label>
              {isMultiview && <span className="text-[9px] text-text-muted">{t('hunyuan.frontRequired')}</span>}
            </div>
            <div className="grid grid-cols-4 gap-2">
              {(['front', 'left', 'right', 'back'] as ViewName[]).map(view => (
                <HunyuanViewField
                  key={view}
                  view={view}
                  value={views[view]}
                  disabled={!isMultiview && view !== 'front'}
                  required={isMultiview && view === 'front'}
                  items={imageSources}
                  onChoose={item => chooseView(view, item)}
                />
              ))}
            </div>
            {!isMultiview && <p role="note" className="mt-2 text-[10px] text-text-muted">✕ {t(selectedModel?.multiview_reason === 'camera_contract' ? 'engines.cameraContract' : 'engines.singleImage')}</p>}
          </div>

          <Hunyuan3DAdvancedSettings
            external3d={external3d}
            textureMode={textureMode}
            setTextureMode={setTextureMode}
            outputFormat={outputFormat}
            setOutputFormat={setOutputFormat}
            operation={operation}
            capabilities={capabilities}
            selectedModel={selectedModel}
            steps={steps}
            setSteps={setSteps}
            guidance={guidance}
            setGuidance={setGuidance}
            octree={octree}
            setOctree={setOctree}
            chunks={chunks}
            setChunks={setChunks}
            seed={seed}
            setSeed={setSeed}
            mcAlgo={mcAlgo}
            setMcAlgo={setMcAlgo}
            textureResolution={textureResolution}
            setTextureResolution={setTextureResolution}
            reduceFace={reduceFace}
            setReduceFace={setReduceFace}
            targetFaces={targetFaces}
            setTargetFaces={setTargetFaces}
            cpuOffload={cpuOffload}
            setCpuOffload={setCpuOffload}
            flashvdm={flashvdm}
            setFlashvdm={setFlashvdm}
            removeBackground={removeBackground}
            setRemoveBackground={setRemoveBackground}
            compile={compile}
            setCompile={setCompile}
          />

          {job && (
            <div className={`rounded-lg border p-3 ${job.status === 'failed' ? 'border-red-500/30 bg-red-500/10' : 'border-border bg-bg-tertiary'}`}>
              <div className="flex items-center justify-between text-[10px]"><span className="text-text-secondary">{job.message}</span><span className="text-text-muted">{Math.round(job.progress * 100)}%</span></div>
              <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden mt-2"><div className="h-full bg-accent-green transition-all" style={{ width: `${Math.max(2, job.progress * 100)}%` }} /></div>
              {job.error && <p className="text-[10px] text-red-300 mt-2 whitespace-pre-wrap max-h-24 overflow-y-auto">{job.error}</p>}
            </div>
          )}
          {error && <p className="text-[10px] text-red-400 whitespace-pre-wrap">{error}</p>}

          {isRunning ? (
            <button onClick={() => void cancel()} className="w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 text-xs font-medium"><Square size={13} /> {operation === 'retexture' ? t('hunyuan.cancelRetexture') : t('hunyuan.cancelGeneration')}</button>
          ) : (
            <button disabled={!canRun} onClick={() => void run()} className={`w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition-all ${canRun ? 'bg-cta hover:brightness-110 shadow-accent-glow text-white' : 'bg-bg-tertiary border border-border text-text-muted cursor-not-allowed'}`}><Play size={13} fill={canRun ? 'currentColor' : 'none'} /> {operation === 'retexture' ? t('hunyuan.createCopy') : t('hunyuan.generateAsset')}</button>
          )}
          <p className="text-[9px] text-text-muted text-center">{t('hunyuan.firstUse')}</p>
        </>
      )}
    </div>
  )
}
