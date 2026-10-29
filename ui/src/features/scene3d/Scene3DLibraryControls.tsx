import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { fetchOutputs, type ApiOutput } from '../../api/outputs'
import { AssetExplorerDialog } from '../../components/common/AssetExplorerDialog'
import { useUiTranslation } from '../../i18n'
import { listWorld3DWorkingScenes } from '../../api/world3dWorkspace'
import { isWorld3DOutput, saveWorld3DOutput } from './sceneLibrary'
import { loadLibraryItem, workingSceneItem } from './workingScenes'
import type { Scene3DDocumentRef } from './documentHistory.ts'
import type { Scene3DDocument } from './types'

export function Scene3DLibraryControls({ document, workspace, disabled, preview, identity, onLoad, onSaved, onCheckpoint, checkpointLabel }: {
  document: Scene3DDocument; workspace: string; disabled: boolean
  preview: () => string | undefined
  identity?: Scene3DDocumentRef
  onLoad: (document: Scene3DDocument, source?: Scene3DDocumentRef) => void
  onSaved?: (output: ApiOutput, document: Scene3DDocument, identity: Scene3DDocumentRef) => void
  onCheckpoint?: () => void
  checkpointLabel?: string
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false)
  const [items, setItems] = useState<ApiOutput[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [retry, setRetry] = useState(0), [name, setName] = useState('')
  const [note, setNote] = useState(''), [error, setError] = useState(''), [menu, setMenu] = useState(false)
  const current = useRef({ document, workspace, disabled, identity })
  current.current = { document, workspace, disabled, identity }
  const loading = useRef<AbortController | null>(null)
  useEffect(() => () => { loading.current?.abort() }, [])
  useEffect(() => {
    loading.current?.abort(); setOpen(false); setBusy(false); setNote(''); setError('')
  }, [workspace])
  useEffect(() => {
    if (!open) return
    const abort = new AbortController()
    setStatus('loading')
    void fetchOutputs(0, 0, { mediaType: 'scene', workspace, signal: abort.signal }).then(result => {
      if (abort.signal.aborted) return
      setItems(result.outputs.filter(isWorld3DOutput)); setStatus('ready')
      // Then the working scenes an agent made and did not publish: they open too.
      void listWorld3DWorkingScenes(workspace, abort.signal).then(working => {
        if (abort.signal.aborted || !working.length) return
        setItems(current => [...current, ...working.map(scene => workingSceneItem(scene,
          t(scene.published ? 'library.workingChanged' : 'library.workingScene', { title: scene.title, revision: scene.revision })))])
      }).catch(() => undefined)
    }).catch(() => { if (!abort.signal.aborted) setStatus('error') })
    return () => abort.abort()
  }, [open, workspace, retry, t])
  const choose = async (item: ApiOutput | null) => {
    if (!item) return
    const captured = current.current, abort = new AbortController()
    loading.current?.abort(); loading.current = abort
    setBusy(true); setError('')
    try {
      const next = await loadLibraryItem(item, captured.workspace, abort.signal)
      if (abort.signal.aborted) return
      if (current.current.document !== captured.document || current.current.workspace !== captured.workspace || current.current.disabled) {
        setError(t('library.changed')); return
      }
      onLoad(next, { workspace: captured.workspace, documentId: item.name, revision: Math.max(1, Math.trunc(item.created_at) || 1) })
      setOpen(false); setNote('')
    } catch { if (!abort.signal.aborted) setError(t('invalidDocument')) }
    finally { if (loading.current === abort) { loading.current = null; setBusy(false) } }
  }
  const save = async () => {
    const captured = current.current
    setBusy(true); setError(''); setNote('')
    try {
      const png = preview()
      if (!png) throw new Error(t('library.previewUnavailable'))
      const saved = await saveWorld3DOutput(captured.document, png, name.trim() || captured.document.templateId, captured.workspace)
      if (captured.identity) onSaved?.(saved, captured.document, captured.identity)
      if (current.current.workspace === captured.workspace) setNote(t('library.saved'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('library.saveFailed')) }
    finally { setBusy(false) }
  }
  const split = Boolean(onCheckpoint && checkpointLabel)
  return <>
    <input aria-label={t('library.name')} placeholder={t('library.name')} value={name} maxLength={120} disabled={disabled || busy}
      onChange={event => setName(event.target.value)} className="h-8 min-w-24 flex-1 rounded-lg border border-border bg-bg-primary px-2" />
    <button type="button" aria-label={t('library.open')} disabled={disabled || busy} onClick={() => { setError(''); setOpen(true) }} className="inline-flex h-8 shrink-0 items-center rounded-lg border border-border px-2">{t('library.openShort')}</button>
    <div className="relative inline-flex shrink-0">
      <button type="button" aria-label={t('library.save')} disabled={disabled || busy} onClick={() => void save()} className={`inline-flex h-8 items-center border border-border px-2 ${split ? 'rounded-l-lg' : 'rounded-lg'}`}>{t('library.saveShort')}</button>
      {split && <button type="button" aria-label={t('library.saveMenu')} aria-haspopup="menu" aria-expanded={menu} data-testid="scene3d-save-menu" disabled={disabled || busy} onClick={() => setMenu(open => !open)} className="inline-flex h-8 items-center rounded-r-lg border border-l-0 border-border px-1.5"><ChevronDown size={14} aria-hidden="true" /></button>}
      {split && menu && <div role="menu" className="absolute right-0 top-full z-30 mt-1 min-w-52 rounded-lg border border-border bg-bg-primary p-1 shadow-lg">
        <button type="button" role="menuitem" data-testid="scene3d-history-checkpoint" disabled={disabled} className="block w-full rounded px-2 py-1.5 text-left text-xs text-text-primary" onClick={() => { setMenu(false); onCheckpoint?.() }}>{checkpointLabel}</button>
      </div>}
    </div>
    {busy && loading.current && <button type="button" className="min-h-10 rounded-lg border border-border px-3"
      onClick={() => { loading.current?.abort(); loading.current = null; setBusy(false) }}>{t('library.cancelLoad')}</button>}
    {note && <span role="status" className="max-w-32 shrink truncate">{note}</span>}{error && <span role="alert" className="max-w-32 shrink truncate text-amber-200">{error}</span>}
    <AssetExplorerDialog open={open} title={t('library.open')} subtitle={t('library.help')} items={items}
      workspaceId={workspace} remote={false} constraints={{ kinds: ['scene'], maxCount: 1, optional: false }} status={busy ? 'loading' : status}
      onRetry={() => setRetry(value => value + 1)} onChoose={item => { if (!busy && !disabled) void choose(item) }}
      onClose={() => setOpen(false)} />
  </>
}
