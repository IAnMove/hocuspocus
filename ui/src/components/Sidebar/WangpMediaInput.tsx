import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput'
import { localEditFile, localEditPreview } from '../../lib/localEditImages'
import { useStore } from '../../stores/useStore'

/** Keep the canonical URL, including its upload root or workspace, as identity. */
export function WangpMediaInput({ label, kind, path, url, keepLocal, onChoose }: {
  label: string
  kind: 'image' | 'video' | 'audio'
  path?: string
  url?: string
  keepLocal?: boolean
  onChoose: (item: ApiOutput | null) => void
}) {
  const workspace = useStore(s => s.activeWorkspace)
  const display = localEditPreview(url || path)
  const localFile = localEditFile(url || path)
  const value: ApiOutput | undefined = path ? {
    name: localFile?.name || path.split('/').pop()?.split('?')[0] || path, type: kind, mode: null,
    size: localFile?.size || 0, created_at: 0, url: display, thumbnail_url: kind === 'image' ? display : '', workspace_id: workspace,
  } : undefined
  // The remote explorer loads one filtered page when opened. Do not scan the
  // library eagerly for every source/mask control in the form.
  return <AssetInput label={label} placeholder={label} items={[]} value={value}
    accept={`${kind}/*`} optional keepLocal={keepLocal} workspaceId={workspace}
    constraints={{ kinds: [kind], maxCount: 1, optional: true }} onChoose={onChoose} />
}
