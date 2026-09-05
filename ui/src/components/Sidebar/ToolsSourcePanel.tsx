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
  imageAssetsError: boolean
  sourceUploadError: boolean
  selectImageAsset: (assetId: string) => void
}

export function ToolsSourcePanel(props: SourceProps) {
  const { t } = useUiTranslation('studio')
  return (
    <div className="space-y-2">
      <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
        {props.tool === 'remove_background'
          ? t('tools.sourceImage')
          : props.tool === 'upscale' ? t('tools.sourceMedia') : t('tools.sourceClip')}
      </label>
      {props.sourcePath && <SelectedSource {...props} />}
      {(!props.sourcePath || props.tool === 'upscale' || props.tool === 'remove_background') && (
        <SourceChooser {...props} />
      )}
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
    ? <div className="overflow-hidden rounded-md bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px]">
      <img src={url} alt={name} className="w-full max-h-64 object-contain" />
    </div>
    : <video src={url} className="w-full rounded-md max-h-64 bg-black" muted controls playsInline />
}

function imageAssetDetails(asset: AssetCatalogItem, imageLabel: string): string {
  const details = [imageLabel]
  const manifest = asset.manifest
  const technical = manifest && typeof manifest.technical === 'object' && manifest.technical !== null
    ? manifest.technical as Record<string, unknown>
    : null
  const media = manifest && typeof manifest.asset === 'object' && manifest.asset !== null
    && typeof (manifest.asset as Record<string, unknown>).media === 'object'
    && (manifest.asset as Record<string, unknown>).media !== null
    ? (manifest.asset as Record<string, unknown>).media as Record<string, unknown>
    : null
  const width = Number(technical?.width ?? technical?.width_px ?? media?.width)
  const height = Number(technical?.height ?? technical?.height_px ?? media?.height)
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    details.push(`${Math.round(width)}×${Math.round(height)}`)
  }
  return details.join(' · ')
}

function SourceChooser(props: SourceProps) {
  const { t } = useUiTranslation('studio')
  const {
    tool, fileRef, uploading, handleSourceUpload, currentIsVideo, useCurrentClip,
    sourceUploadError,
  } = props
  return (
    <div className="space-y-2">
      <div
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed border-border rounded-lg p-3 text-center cursor-pointer hover:border-accent-blue transition-colors ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
      >
        <Upload size={16} className="mx-auto mb-1 text-text-muted" />
        <p className="text-[11px] text-text-secondary">{uploading ? t('chrome.uploading') : tool === 'remove_background' ? t('tools.uploadImage') : tool === 'upscale' ? t('tools.uploadMedia') : t('tools.uploadClip')}</p>
        <input
          ref={fileRef}
          type="file"
          accept={tool === 'remove_background' ? 'image/*' : tool === 'upscale' ? 'image/*,video/*' : 'video/*'}
          className="hidden"
          onChange={event => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) void handleSourceUpload(file)
          }}
        />
      </div>
      {sourceUploadError && (
        <p className="text-[10px] text-red-400" role="status">{t('tools.sourceUploadFailed')}</p>
      )}
      {tool === 'remove_background' || tool === 'upscale'
        ? <ImageSourceChooser {...props} showVideo={tool === 'upscale'} />
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
  currentIsImage, useCurrentImage, currentIsVideo, useCurrentClip, imageAssets,
  imageAssetsLoading, imageAssetsError, sourceAssetId, selectImageAsset, showVideo,
}: SourceProps & { showVideo?: boolean }) {
  const { t } = useUiTranslation('studio')
  const imageTypeLabel = String(t('tools.imageAssetType'))
  return (
    <>
      <div
        className="grid max-h-72 grid-cols-3 gap-2 overflow-y-auto pr-1"
        role="list"
        aria-label={String(t(showVideo ? 'tools.sourceMedia' : 'tools.sourceImage'))}
      >
        {imageAssets.map(asset => {
          const location = asset.locations[0]
          const previewUrl = location?.url || asset.url
          const selected = sourceAssetId === asset.id
          return (
            <button
              key={asset.id}
              type="button"
              aria-label={`${t('tools.selectImageAsset')} ${asset.filename}`}
              aria-pressed={selected}
              onClick={() => selectImageAsset(asset.id)}
              className={`overflow-hidden rounded-md border text-left transition-colors ${selected ? 'border-accent-blue ring-1 ring-accent-blue' : 'border-border hover:border-accent-blue'}`}
            >
              <div className="aspect-square bg-black">
                <img src={previewUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
              </div>
              <span className="block min-w-0 px-1.5 py-1">
                <span className="block truncate text-[10px] text-text-secondary" title={asset.filename}>
                  {asset.filename}
                </span>
                <span className="block truncate text-[9px] text-text-muted">
                  {imageAssetDetails(asset, imageTypeLabel)}
                </span>
              </span>
            </button>
          )
        })}
      </div>
      {imageAssetsLoading && (
        <p className="text-[10px] text-text-muted" aria-live="polite">{t('tools.loadingImages')}</p>
      )}
      {!imageAssetsLoading && !imageAssetsError && imageAssets.length === 0 && (
        <p className="text-[10px] text-text-muted">{t('tools.selectGalleryImage')}</p>
      )}
      {imageAssetsError && (
        <p className="text-[10px] text-red-400" role="status">{t('tools.imageAssetsFailed')}</p>
      )}
      <button
        onClick={useCurrentImage}
        disabled={!currentIsImage}
        className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {currentIsImage ? t('tools.useGalleryImage') : t('tools.selectGalleryImage')}
      </button>
      {showVideo && (
        <button
          onClick={useCurrentClip}
          disabled={!currentIsVideo}
          className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {currentIsVideo ? t('tools.useGallery') : t('tools.selectGallery')}
        </button>
      )}
    </>
  )
}
