import { useEffect, useRef, useState } from 'react'
import { Wrench, Upload, X, Film, Image as ImageIcon, Mic, Play } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import type { AssetCatalogItem } from '../../api/assets'

// Upscale methods — same set as Post Processing's Spatial Upsampling, minus the
// VAE options (those are tied to the generation pipeline, not a standalone clip).
const upscaleMethods = [
  { value: 'flashvsr2', label: 'FlashVSR 2x' },
  { value: 'flashvsr3', label: 'FlashVSR 3x' },
  { value: 'flashvsr4', label: 'FlashVSR 4x' },
  { value: 'flashvsr2pass2', label: 'FlashVSR Two Pass 2x' },
  { value: 'flashvsr2pass4', label: 'FlashVSR Two Pass 4x' },
  { value: 'lanczos1.5', label: 'Lanczos 1.5x (fast)' },
  { value: 'lanczos2', label: 'Lanczos 2x (fast)' },
]

export function ToolsPanel() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
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
  }, [tool])

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

      {/* Source media — upload, select an exact catalog asset, or use the current gallery item. */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {tool === 'remove_background' ? t('tools.sourceImage') : t('tools.sourceClip')}
        </label>
        {sourcePath ? (
          <div className="bg-bg-tertiary border border-border rounded-lg p-2 space-y-2">
            {sourceUrl && (
              sourceKind === 'image'
                ? <img src={sourceUrl} alt={sourceName || ''} className="w-full rounded-md max-h-44 object-contain bg-black" />
                : <video src={sourceUrl} className="w-full rounded-md max-h-44 bg-black" muted controls playsInline />
            )}
            <div className="flex items-center gap-2">
              {sourceKind === 'image' ? <ImageIcon size={12} className="text-accent-blue shrink-0" /> : <Film size={12} className="text-accent-blue shrink-0" />}
              <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{sourceName}</span>
              {sourceAssetId && <span className="text-[9px] text-text-muted shrink-0">{sourceWorkspace || 'workspace'}</span>}
              <button onClick={() => setSource(null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={t('chrome.clear')}>
                <X size={12} />
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <div
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed border-border rounded-lg p-3 text-center cursor-pointer hover:border-accent-blue transition-colors ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
            >
              <Upload size={16} className="mx-auto mb-1 text-text-muted" />
              <p className="text-[11px] text-text-secondary">{uploading ? t('chrome.uploading') : tool === 'remove_background' ? t('tools.uploadImage') : t('tools.uploadClip')}</p>
              <input
                ref={fileRef}
                type="file"
                accept={tool === 'remove_background' ? 'image/*' : 'video/*'}
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) handleSourceUpload(f) }}
              />
            </div>
            {tool === 'remove_background' ? (
              <>
                <select
                  aria-label={t('tools.sourceImage')}
                  value={sourceAssetId || ''}
                  onChange={event => selectImageAsset(event.target.value)}
                  className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                  disabled={imageAssetsLoading}
                >
                  <option value="">{imageAssetsLoading ? t('tools.loadingImages') : t('tools.selectGalleryImage')}</option>
                  {imageAssets.map(asset => (
                    <option key={asset.id} value={asset.id}>{asset.filename}</option>
                  ))}
                </select>
                <button
                  onClick={useCurrentImage}
                  disabled={!currentIsImage}
                  className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {currentIsImage ? t('tools.useGalleryImage') : t('tools.selectGalleryImage')}
                </button>
              </>
            ) : (
              <button
                onClick={useCurrentClip}
                disabled={!currentIsVideo}
                className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {currentIsVideo ? t('tools.useGallery') : t('tools.selectGallery')}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Tool params */}
      {tool === 'upscale' ? (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('tools.upscaleMethod')}</label>
          <select
            value={method}
            onChange={e => setMethod(e.target.value)}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            {upscaleMethods.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {flashvsrOff && (
            <p className="text-[10px] text-indicator-warning mt-1.5 leading-snug">
              {t('tools.flashvsrOff')}
            </p>
          )}
          <p className="text-[10px] text-text-muted mt-1.5 leading-snug">
            {t('tools.upscaleHint')}
          </p>
        </div>
      ) : tool === 'revoice' ? (
        <div className="space-y-2">
          <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('tools.replaceVoice')}</label>
          <div className="flex gap-1.5 text-xs">
            {([['single', 'tools.singleVoice'], ['two', 'tools.twoVoices']] as const).map(([val, labelKey]) => (
              <button
                key={val}
                onClick={() => setRevoiceMode(val)}
                className={`flex-1 py-1.5 rounded-md border transition-colors ${
                  revoiceMode === val
                    ? 'bg-accent-blue/10 border-accent-blue text-text-primary'
                    : 'bg-bg-tertiary border-border text-text-secondary hover:text-text-primary'
                }`}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-text-muted leading-snug">
            {revoiceMode === 'single'
              ? t('tools.singleHint')
              : t('tools.twoHint')}
          </p>
          {[0, ...(revoiceMode === 'two' ? [1] : [])].map(idx => {
            const ref = revoiceRefs[idx]
            const label = revoiceMode === 'two' ? (idx === 0 ? t('tools.voiceA') : t('tools.voiceB')) : t('tools.referenceVoice')
            return (
              <div key={idx}>
                <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1 block">{label}</label>
                {!ref || !ref.path ? (
                  <div
                    onClick={() => vcFileRefs[idx].current?.click()}
                    className={`border-2 border-dashed border-border rounded-lg p-2 text-center cursor-pointer hover:border-accent-blue transition-colors ${vcUploading === idx ? 'opacity-50 pointer-events-none' : ''}`}
                  >
                    <p className="text-[11px] text-text-secondary">{vcUploading === idx ? t('chrome.uploading') : t('tools.uploadSample', { label: label.toLowerCase() })}</p>
                    <input
                      ref={vcFileRefs[idx]}
                      type="file"
                      accept="audio/*,video/*"
                      className="hidden"
                      onChange={e => { const f = e.target.files?.[0]; if (f) handleVcUpload(idx, f) }}
                    />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5">
                    <Mic size={12} className="text-accent-blue shrink-0" />
                    <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{ref.filename}</span>
                    <button onClick={() => setRevoiceRef(idx, null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={tCommon('actions.remove')}>
                      <X size={12} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="space-y-2">
          <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('tools.removeBackgroundInstruction')}</label>
          <textarea
            value={removeBackgroundInstruction}
            onChange={event => setRemoveBackgroundInstruction(event.target.value)}
            placeholder={t('tools.removeBackgroundInstructionPlaceholder')}
            rows={3}
            className="w-full resize-y bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
          />
          <p className="text-[10px] text-text-muted leading-snug">{t('tools.removeBackgroundHint')}</p>
        </div>
      )}

      {/* Run */}
      <button
        onClick={() => runTool()}
        disabled={!canRun}
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
