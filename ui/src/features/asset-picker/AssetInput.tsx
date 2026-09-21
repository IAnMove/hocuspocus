import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { FolderOpen, Monitor, X } from 'lucide-react'
import type { ApiOutput } from '../../api/outputs'
import { useUiTranslation } from '../../i18n'
import { AssetPickTrigger } from '../../components/common/AssetPickTrigger.tsx'
import type { AssetConstraints } from './types.ts'
import { rememberLocalImage } from '../../lib/localEditImages'
import { createUploadSession, fileMatchesConstraints } from './upload.ts'

const AssetExplorerDialog = lazy(() =>
  import('../../components/common/AssetExplorerDialog.tsx').then(module => ({ default: module.AssetExplorerDialog })),
)

export function AssetInput({
  label,
  placeholder,
  items,
  value,
  accept,
  optional,
  constraints,
  disabled,
  workspaceId,
  keepLocal,
  showPreview,
  onChoose,
}: {
  label: string
  placeholder: string
  items: ApiOutput[]
  value?: ApiOutput
  accept?: string
  optional?: boolean
  constraints?: AssetConstraints
  disabled?: boolean
  workspaceId?: string
  keepLocal?: boolean
  showPreview?: boolean
  onChoose: (item: ApiOutput | null) => void
}) {
  const { t } = useUiTranslation('common')
  const fileRef = useRef<HTMLInputElement>(null)
  const upload = useRef(createUploadSession())
  const chooseGen = useRef(0)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => () => {
    chooseGen.current += 1
    upload.current.abort()
  }, [])

  const pickLocal = async (file: File | undefined) => {
    if (!file) return
    if (constraints && !fileMatchesConstraints(file, constraints.kinds)) return
    const generation = ++chooseGen.current
    const scope = workspaceId
    setError('')
    if (keepLocal) {
      const url = rememberLocalImage(file)
      onChoose({
        name: file.name,
        type: 'image',
        mode: null,
        size: file.size,
        created_at: Date.now() / 1000,
        url,
        thumbnail_url: url,
        workspace_id: scope,
      })
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    setBusy(true)
    try {
      const uploaded = await upload.current.run(file)
      if (generation !== chooseGen.current) return
      onChoose({
        name: uploaded.filename,
        type: uploaded.kind === 'model3d' ? 'model3d' : uploaded.kind === 'audio' ? 'audio' : uploaded.kind === 'video' ? 'video' : 'image',
        mode: null,
        size: file.size,
        created_at: Date.now() / 1000,
        url: uploaded.url,
        thumbnail_url: uploaded.kind === 'image' ? uploaded.url : '',
        workspace_id: scope,
        path: uploaded.path,
      })
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      if (generation !== chooseGen.current) return
      setError(t('picker.uploadFailed'))
    } finally {
      if (generation === chooseGen.current) setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-1" onDrop={event => { event.preventDefault(); event.stopPropagation(); if (!disabled && !busy) void pickLocal(event.dataTransfer.files[0]) }} onDragOver={event => event.preventDefault()}>
      <AssetPickTrigger label={label} selected={value} showPreview={showPreview} placeholder={busy ? t('picker.uploading') : placeholder} disabled={disabled || busy} onOpen={() => setOpen(true)} />
      <div className="flex flex-wrap gap-1">
        <button type="button" disabled={disabled || busy} onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary disabled:opacity-40">
          <Monitor size={10} />{t('picker.fromDevice')}
        </button>
        <button type="button" disabled={disabled || busy} onClick={() => setOpen(true)} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary disabled:opacity-40">
          <FolderOpen size={10} />{t('picker.fromLibrary')}
        </button>
        {optional && value && (
          <button type="button" disabled={disabled || busy} onClick={() => onChoose(null)} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary disabled:opacity-40">
            <X size={10} />{t('picker.remove')}
          </button>
        )}
      </div>
      {error && <p className="text-[9px] text-red-300">{error}</p>}
      <input
        ref={fileRef}
        type="file"
        accept={accept}
        className="hidden"
        data-testid="asset-input-file"
        onChange={event => { void pickLocal(event.target.files?.[0]) }}
      />
      {open ? (
        <Suspense fallback={<div className="fixed inset-0 z-[130] bg-black/70" />}>
          <AssetExplorerDialog
            open={open}
            title={label}
            items={items}
            selected={value}
            workspaceId={workspaceId}
            remote={Boolean(workspaceId)}
            allowNone={optional}
            constraints={constraints}
            onClose={() => setOpen(false)}
            onChoose={item => { onChoose(item); setOpen(false) }}
          />
        </Suspense>
      ) : null}
    </div>
  )
}
