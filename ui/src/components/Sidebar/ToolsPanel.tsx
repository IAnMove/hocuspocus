import { useEffect, useRef, useState } from 'react'
import { Wrench, Play } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import type { AssetCatalogItem } from '../../api/assets'
import { ToolsParamsPanel } from './ToolsParamsPanel'
import { ToolsSourcePanel } from './ToolsSourcePanel'

export function ToolsPanel() {
  const { t } = useUiTranslation('studio')
  const tool = useStore(s => s.toolsTool)
  const setTool = useStore(s => s.setToolsTool)
  const sourcePath = useStore(s => s.toolsSourcePath)
  const sourceName = useStore(s => s.toolsSourceName)
  const sourceUrl = useStore(s => s.toolsSourceUrl)
  const sourceAssetId = useStore(s => s.toolsSourceAssetId)
  const sourceWorkspace = useStore(s => s.toolsSourceWorkspace)
  const sourceKind = useStore(s => s.toolsSourceKind)
  const setSource = useStore(s => s.setToolsSource)
  const method = useStore(s => s.toolsUpscaleMethod)
  const setMethod = useStore(s => s.setToolsUpscaleMethod)
  const revoiceMode = useStore(s => s.toolsRevoiceMode)
  const setRevoiceMode = useStore(s => s.setToolsRevoiceMode)
  const revoiceRefs = useStore(s => s.toolsRevoiceRefs)
  const setRevoiceRef = useStore(s => s.setToolsRevoiceRef)
  const removeBackgroundInstruction = useStore(s => s.toolsRemoveBackgroundInstruction)
  const setRemoveBackgroundInstruction = useStore(s => s.setToolsRemoveBackgroundInstruction)
  const toolsAssetsRevision = useStore(s => s.toolsAssetsRevision)
  const toolsSubmitting = useStore(s => s.toolsSubmitting)
  const runTool = useStore(s => s.runTool)
  const outputs = useStore(s => s.outputs)
  const selectedOutput = useStore(s => s.selectedOutput)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const flashvsrMode = useStore(s => s.servicesConfig?.flashvsr_mode ?? 1)
  const current = outputs[selectedOutput]
  const currentIsVideo = !!current && current.type === 'video'

  const fileRef = useRef<HTMLInputElement>(null)
  const vcFileRefs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)]
  const [uploading, setUploading] = useState(false)
  const [vcUploading, setVcUploading] = useState<number | null>(null)
  const [imageAssets, setImageAssets] = useState<AssetCatalogItem[]>([])
  const [imageAssetsLoading, setImageAssetsLoading] = useState(false)

  useEffect(() => {
    if (tool !== 'remove_background') return
    const controller = new AbortController()
    setImageAssetsLoading(true)
    api.fetchAssets({ kind: 'image', limit: 100, signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) setImageAssets(result.assets)
      })
      .catch(error => {
        if (!controller.signal.aborted) console.error('Image asset catalog failed:', error)
      })
      .finally(() => {
        if (!controller.signal.aborted) setImageAssetsLoading(false)
      })
    return () => controller.abort()
  }, [tool, toolsAssetsRevision])

  const handleSourceUpload = async (file: File) => {
    setUploading(true)
    try {
      const r = await api.uploadImage(file)  // /api/v1/upload handles video too
      setSource({
        path: r.path,
        name: file.name,
        url: r.url,
        workspace: tool === 'remove_background' ? '__uploads__' : null,
        kind: tool === 'remove_background' ? 'image' : 'video',
      })
    } catch (e) {
      console.error('Source upload failed:', e)
    } finally {
      setUploading(false)
    }
  }

  const useCurrentClip = () => {
    if (currentIsVideo) setSource({ path: current.name, name: current.name, url: current.url, kind: 'video' })
  }

  const useCurrentImage = () => {
    if (currentIsImage) setSource({ path: current.name, name: current.name, url: current.url, kind: 'image' })
  }

  const selectImageAsset = (assetId: string) => {
    const asset = imageAssets.find(item => item.id === assetId)
    if (!asset) {
      setSource(null)
      return
    }
    const location = asset.locations.find(item => item.workspace_id === activeWorkspace)
      || asset.locations[0]
    if (!location) {
      setSource(null)
      return
    }
    setSource({
      path: location.filename,
      name: asset.filename,
      url: location.url || asset.url,
      assetId: asset.id,
      workspace: location.workspace_id,
      kind: 'image',
    })
  }

  const handleVcUpload = async (index: number, file: File) => {
    setVcUploading(index)
    try {
      const r = await api.uploadAudio(file)
      setRevoiceRef(index, { filename: file.name, path: r.path })
    } catch (e) {
      console.error('Voice ref upload failed:', e)
    } finally {
      setVcUploading(null)
    }
  }

  const hasRefs = revoiceRefs.some(r => r && r.path)
  const currentIsImage = !!current && current.type === 'image'
  const canRun = !!sourcePath && (tool === 'upscale' || hasRefs || (tool === 'remove_background' && sourceKind === 'image'))
  const flashvsrOff = flashvsrMode === 0 && method.startsWith('flashvsr')

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-1.5 text-[11px] text-text-muted uppercase tracking-wider mb-2">
          <Wrench size={12} /> {t('tools.title')}
        </div>
        {/* Tool selector */}
        <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
          {([['upscale', 'tools.upscale'], ['revoice', 'tools.revoice'], ['remove_background', 'tools.removeBackground']] as const).map(([val, labelKey]) => (
            <button
              key={val}
              onClick={() => setTool(val)}
              className={`flex-1 text-xs py-2 rounded-md transition-all ${
                tool === val ? 'bg-bg-active text-text-primary' : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
      </div>

      <ToolsSourcePanel
        tool={tool}
        sourcePath={sourcePath}
        sourceName={sourceName}
        sourceUrl={sourceUrl}
        sourceAssetId={sourceAssetId}
        sourceWorkspace={sourceWorkspace}
        sourceKind={sourceKind}
        setSource={setSource}
        fileRef={fileRef}
        uploading={uploading}
        handleSourceUpload={handleSourceUpload}
        currentIsImage={currentIsImage}
        currentIsVideo={currentIsVideo}
        useCurrentImage={useCurrentImage}
        useCurrentClip={useCurrentClip}
        imageAssets={imageAssets}
        imageAssetsLoading={imageAssetsLoading}
        selectImageAsset={selectImageAsset}
      />
      {tool === 'remove_background' && !sourcePath && (
        <p className="text-[10px] text-text-muted leading-snug" role="status">
          {t('tools.removeBackgroundNeedsSource')}
        </p>
      )}

      <ToolsParamsPanel
        tool={tool}
        method={method}
        setMethod={setMethod}
        flashvsrOff={flashvsrOff}
        revoiceMode={revoiceMode}
        setRevoiceMode={setRevoiceMode}
        revoiceRefs={revoiceRefs}
        setRevoiceRef={setRevoiceRef}
        vcFileRefs={vcFileRefs}
        vcUploading={vcUploading}
        handleVcUpload={handleVcUpload}
        removeBackgroundInstruction={removeBackgroundInstruction}
        setRemoveBackgroundInstruction={setRemoveBackgroundInstruction}
      />

      {/* Run */}
      <button
        onClick={() => runTool()}
        disabled={!canRun || toolsSubmitting}
        className={`w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 font-medium text-xs transition-all ${
          canRun
            ? 'bg-cta hover:brightness-110 shadow-accent-glow text-white'
            : 'bg-bg-tertiary text-text-muted cursor-not-allowed border border-border'
        }`}
      >
        <Play size={13} fill={canRun ? 'white' : 'currentColor'} />
        {tool === 'upscale' ? t('tools.upscaleClip') : tool === 'revoice' ? t('tools.replaceVoiceAction') : t('tools.removeBackgroundAction')}
      </button>
    </div>
  )
}
