import type { RefObject } from 'react'
import { Film, Image as ImageIcon, Upload, X } from 'lucide-react'
import type { AssetCatalogItem } from '../../api/assets'
import { useUiTranslation } from '../../i18n'

export type ToolsPanelTool = 'upscale' | 'revoice' | 'remove_background'
export type ToolSource = {
  path: string
  name: string
  url: string | null
  assetId?: string | null
  workspace?: string | null
  kind?: 'image' | 'video' | 'audio' | 'model3d' | null
}

type SourceProps = {
  tool: ToolsPanelTool
  sourcePath: string | null
  sourceName: string | null
  sourceUrl: string | null
  sourceAssetId: string | null
  sourceWorkspace: string | null
  sourceKind: ToolSource['kind']
  setSource: (source: ToolSource | null) => void
  fileRef: RefObject<HTMLInputElement | null>
  uploading: boolean
  handleSourceUpload: (file: File) => Promise<void>
  currentIsImage: boolean
  currentIsVideo: boolean
  useCurrentImage: () => void
  useCurrentClip: () => void
  imageAssets: AssetCatalogItem[]
  imageAssetsLoading: boolean
  selectImageAsset: (assetId: string) => void
}

export function ToolsSourcePanel(props: SourceProps) {
  const { t } = useUiTranslation('studio')
  return (
    <div>
      <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
        {props.tool === 'remove_background' ? t('tools.sourceImage') : t('tools.sourceClip')}
      </label>
      {props.sourcePath
        ? <SelectedSource {...props} />
        : <SourceChooser {...props} />}
    </div>
  )
}

function SelectedSource({
  sourceUrl, sourceKind, sourceName, sourceAssetId, sourceWorkspace, setSource,
}: SourceProps) {
  const { t } = useUiTranslation('studio')
  return (
    <div className="bg-bg-tertiary border border-border rounded-lg p-2 space-y-2">
      {sourceUrl && <SourcePreview url={sourceUrl} kind={sourceKind} name={sourceName || ''} />}
      <div className="flex items-center gap-2">
        {sourceKind === 'image'
          ? <ImageIcon size={12} className="text-accent-blue shrink-0" />
          : <Film size={12} className="text-accent-blue shrink-0" />}
        <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{sourceName}</span>
        {sourceAssetId && <span className="text-[9px] text-text-muted shrink-0">{sourceWorkspace || 'workspace'}</span>}
        <button onClick={() => setSource(null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={t('chrome.clear')}>
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

function SourcePreview({ url, kind, name }: { url: string; kind: ToolSource['kind']; name: string }) {
  return kind === 'image'
    ? <img src={url} alt={name} className="w-full rounded-md max-h-44 object-contain bg-black" />
    : <video src={url} className="w-full rounded-md max-h-44 bg-black" muted controls playsInline />
}

function SourceChooser(props: SourceProps) {
  const { t } = useUiTranslation('studio')
  const { tool, fileRef, uploading, handleSourceUpload, currentIsVideo, useCurrentClip } = props
  return (
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
          onChange={event => { const file = event.target.files?.[0]; if (file) void handleSourceUpload(file) }}
        />
      </div>
      {tool === 'remove_background'
        ? <ImageSourceChooser {...props} />
        : <button
          onClick={useCurrentClip}
          disabled={!currentIsVideo}
          className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {currentIsVideo ? t('tools.useGallery') : t('tools.selectGallery')}
        </button>}
    </div>
  )
}

function ImageSourceChooser({
  currentIsImage, useCurrentImage, imageAssets, imageAssetsLoading, sourceAssetId, selectImageAsset,
}: SourceProps) {
  const { t } = useUiTranslation('studio')
  return (
    <>
      <select
        aria-label={String(t('tools.sourceImage'))}
        value={sourceAssetId || ''}
        onChange={event => selectImageAsset(event.target.value)}
        className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
        disabled={imageAssetsLoading}
      >
        <option value="">{imageAssetsLoading ? t('tools.loadingImages') : t('tools.selectGalleryImage')}</option>
        {imageAssets.map(asset => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}
      </select>
      <button
        onClick={useCurrentImage}
        disabled={!currentIsImage}
        className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {currentIsImage ? t('tools.useGalleryImage') : t('tools.selectGalleryImage')}
      </button>
    </>
  )
}
