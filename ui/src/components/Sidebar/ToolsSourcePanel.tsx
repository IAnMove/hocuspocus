import { Film, Image as ImageIcon, X } from 'lucide-react'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import type { AssetKind } from '../../api/assets'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { ImagePreview } from '../common/ImagePreview'

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
  currentIsImage: boolean
  currentIsVideo: boolean
  useCurrentImage: () => void
  useCurrentClip: () => void
  sourceUploadError: boolean
  items: ApiOutput[]
  onChoose: (item: ApiOutput | null) => void
}

const SOURCE_KINDS: Record<ToolsPanelTool, readonly AssetKind[]> = {
  remove_background: ['image', 'video'],
  upscale: ['image', 'video'],
  revoice: ['video'],
}

const SOURCE_ACCEPT: Record<ToolsPanelTool, string> = {
  remove_background: 'image/*,video/*',
  upscale: 'image/*,video/*',
  revoice: 'video/*',
}

export function ToolsSourcePanel(props: SourceProps) {
  const { t } = useUiTranslation('studio')
  const workspaceId = useStore(s => s.activeWorkspace)
  const label = props.tool === 'revoice' ? t('tools.sourceClip') : t('tools.sourceMedia')
  const value = sourceValue(props)
  return (
    <div className="space-y-2">
      <AssetInput
        label={label}
        placeholder={props.tool === 'revoice' ? t('tools.selectGallery') : t('tools.selectLibraryMedia')}
        items={props.items}
        value={value}
        showPreview={false}
        accept={SOURCE_ACCEPT[props.tool]}
        workspaceId={workspaceId}
        optional
        constraints={{ kinds: SOURCE_KINDS[props.tool], maxCount: 1, optional: true }}
        onChoose={props.onChoose}
      />
      {props.sourcePath && <SelectedSource {...props} />}
      {props.sourceUploadError && (
        <p className="text-[10px] text-red-400" role="status">{t('tools.sourceUploadFailed')}</p>
      )}
      {(props.tool === 'remove_background' || props.tool === 'upscale') && (
        <button
          type="button"
          onClick={props.useCurrentImage}
          disabled={!props.currentIsImage}
          className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {props.currentIsImage ? t('tools.useGalleryImage') : t('tools.selectGalleryImage')}
        </button>
      )}
      <button
        type="button"
        onClick={props.useCurrentClip}
        disabled={!props.currentIsVideo}
        className="w-full text-[11px] py-1.5 rounded-md border border-border bg-bg-tertiary text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {props.currentIsVideo ? t('tools.useGallery') : t('tools.selectGallery')}
      </button>
    </div>
  )
}

function sourceValue(props: SourceProps): ApiOutput | undefined {
  if (!props.sourcePath) return undefined
  const type = props.sourceKind === 'video' ? 'video' : 'image'
  return {
    name: props.sourceName || props.sourcePath,
    type,
    mode: null,
    size: 0,
    created_at: 0,
    url: props.sourceUrl || '',
    thumbnail_url: type === 'image' ? props.sourceUrl || '' : '',
  }
}

function SelectedSource({
  sourceUrl, sourceKind, sourceName, sourceAssetId, sourceWorkspace, setSource,
}: SourceProps) {
  const { t } = useUiTranslation('studio')
  return (
    <div className="bg-bg-tertiary border border-border rounded-lg p-2 space-y-2">
      {sourceUrl && <SourcePreview url={sourceUrl} kind={sourceKind} name={sourceName || ''} workspace={sourceWorkspace} />}
      <div className="flex items-center gap-2">
        {sourceKind === 'image'
          ? <ImageIcon size={12} className="text-accent-blue shrink-0" />
          : <Film size={12} className="text-accent-blue shrink-0" />}
        <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{sourceName}</span>
        {sourceAssetId && <span className="text-[9px] text-text-muted shrink-0">{sourceWorkspace || 'workspace'}</span>}
        <button type="button" onClick={() => setSource(null)} className="p-0.5 text-text-muted hover:text-red-400 transition-colors" title={t('chrome.clear')}>
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

function SourcePreview({ url, kind, name, workspace }: { url: string; kind: ToolSource['kind']; name: string; workspace?: string | null }) {
  return kind === 'image'
    ? <div className="overflow-hidden rounded-md bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px]">
      <ImagePreview image={{ url, name, workspace_id: workspace || undefined }} className="block w-full">
        <img src={url} alt={name} className="w-full max-h-64 object-contain" />
      </ImagePreview>
    </div>
    : <div className="rounded-md bg-[conic-gradient(#1c2330_25%,#343d4c_0_50%,#1c2330_0_75%,#343d4c_0)] bg-[length:16px_16px]"><video src={url} className="w-full rounded-md max-h-64" muted controls playsInline /></div>
}
